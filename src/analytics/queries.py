"""
Shared database query layer for dashboards.

Returns pandas DataFrames for use in Streamlit visualizations.
All heavy lifting happens in SQL; Python just orchestrates.
"""

import pandas as pd
from datetime import date, datetime, time, timedelta
from sqlalchemy import text

from src.config import engine


def _q(sql: str, params: dict = None) -> pd.DataFrame:
    """Execute a SQL query and return a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def _trusted_labor_subquery(alias: str = "l") -> str:
    """
    Return a SQL subquery alias scoped to labor rows imported successfully
    from Lightspeed labor CSV files.
    """
    return f"""
        (
            SELECT pl.*
            FROM pos_labor pl
            JOIN import_logs il ON il.id = pl.import_log_id
            WHERE il.import_type = 'labor'
              AND il.status = 'success'
        ) {alias}
    """


def _fixed_labor_for_day_expr(day_expr: str) -> str:
    """
    Correlated SQL expression for fixed daily labor not sourced from POS clock-ins.
    active on a given trading day.
    """
    return f"""
        (
            SELECT COALESCE(SUM(f.daily_amount), 0)
            FROM labor_fixed_daily_costs f
            WHERE f.include_in_projections = TRUE
              AND {day_expr} >= f.effective_start_date
              AND (
                    f.effective_end_date IS NULL
                    OR {day_expr} <= f.effective_end_date
                  )
        )
    """


def _payroll_tax_rate_for_day_expr(day_expr: str) -> str:
    """
    Correlated SQL expression returning the employer payroll tax rate
    (FICA + FUTA + SUTA + workers comp as a decimal fraction of wages)
    in effect on a given trading day. Returns 0 if no row found.
    """
    return f"""
        COALESCE(
            (
                SELECT p.payroll_tax_rate
                FROM payroll_burden_settings p
                WHERE {day_expr} >= p.effective_start_date
                  AND (
                        p.effective_end_date IS NULL
                        OR {day_expr} <= p.effective_end_date
                      )
                ORDER BY p.effective_start_date DESC
                LIMIT 1
            ),
            0
        )
    """


def _payroll_fee_daily_for_day_expr(day_expr: str) -> str:
    """
    Correlated SQL expression returning the daily share of the flat monthly
    payroll service fee in effect on a given trading day.

    Divides payroll_fee_monthly by the number of calendar days in that month
    so the annual total always equals 12 * monthly_fee regardless of which
    days the bar is open.

    DATE_PART returns double precision, so we cast to NUMERIC to keep
    arithmetic consistent with the other NUMERIC columns.
    """
    return f"""
        COALESCE(
            (
                SELECT p.payroll_fee_monthly
                       / CAST(DATE_PART('days',
                             DATE_TRUNC('month', {day_expr})
                             + INTERVAL '1 month'
                             - DATE_TRUNC('month', {day_expr})
                         ) AS NUMERIC)
                FROM payroll_burden_settings p
                WHERE {day_expr} >= p.effective_start_date
                  AND (
                        p.effective_end_date IS NULL
                        OR {day_expr} <= p.effective_end_date
                      )
                ORDER BY p.effective_start_date DESC
                LIMIT 1
            ),
            0
        )
    """


def _payroll_burden_for_wages_and_day_expr(wages_expr: str, day_expr: str) -> str:
    """
    Convenience expression returning the full payroll burden dollar amount
    (tax + daily fee) for a given wages expression and trading day.

    Usage in SQL:
        wages + {_payroll_burden_for_wages_and_day_expr('wages_col', 'trading_day')}
    """
    return f"""
        (
            ({wages_expr}) * {_payroll_tax_rate_for_day_expr(day_expr)}
            + {_payroll_fee_daily_for_day_expr(day_expr)}
        )
    """


# ============================================================================
# DAILY SALES
# ============================================================================


def get_daily_sales(start: date = None, end: date = None) -> pd.DataFrame:
    """Get daily sales summary, optionally filtered by date range."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT trading_day, total_receipts, gross_sales, gross_without_tax,
               net_sales, liquor_tax, sales_tax, fees, total_tax, tax_on_comps,
               total_guests, total_checks, guest_avg, check_avg,
               cash_payments, credit_payments, cash_tips, credit_tips, total_tips,
               total_comps, total_voids
        FROM pos_daily_sales
        {where}
        ORDER BY trading_day
    """, params)


def get_sales_date_range() -> tuple[date, date]:
    """Get min/max trading days with full sales data."""
    df = _q("""
        SELECT MIN(trading_day) as min_date, MAX(trading_day) as max_date
        FROM pos_daily_sales
        WHERE net_sales IS NOT NULL
    """)
    if df.empty:
        today = date.today()
        return today, today
    return df.iloc[0]["min_date"], df.iloc[0]["max_date"]


def get_all_trading_days() -> list[date]:
    """Get all trading days with full sales data."""
    df = _q("""
        SELECT DISTINCT trading_day
        FROM pos_daily_sales
        WHERE net_sales IS NOT NULL
        ORDER BY trading_day DESC
    """)
    return df["trading_day"].tolist()


# ============================================================================
# DAYPART SALES
# ============================================================================


def get_daypart_sales(trading_day: date) -> pd.DataFrame:
    """Get day-part breakdown for a specific trading day."""
    return _q("""
        SELECT day_part, gross_sales, net_sales, guests, checks,
               guest_avg, check_avg
        FROM pos_daily_sales_by_daypart
        WHERE trading_day = :day
        ORDER BY day_part
    """, {"day": trading_day})


def get_daypart_trend(start: date, end: date) -> pd.DataFrame:
    """Get day-part sales over a date range."""
    return _q("""
        SELECT trading_day, day_part, gross_sales, net_sales, guests, checks
        FROM pos_daily_sales_by_daypart
        WHERE trading_day BETWEEN :start AND :end
        ORDER BY trading_day, day_part
    """, {"start": start, "end": end})


# ============================================================================
# CATEGORY SALES
# ============================================================================


def get_category_sales(trading_day: date) -> pd.DataFrame:
    """Get category-level sales for a specific trading day."""
    return _q("""
        SELECT category_name, gross_sales, comps, total_tax, net_sales, receipt_total
        FROM pos_daily_sales_by_category
        WHERE trading_day = :day
        ORDER BY net_sales DESC
    """, {"day": trading_day})


def get_category_trend(start: date, end: date) -> pd.DataFrame:
    """Get category sales over a date range."""
    return _q("""
        SELECT trading_day, category_name, net_sales, gross_sales
        FROM pos_daily_sales_by_category
        WHERE trading_day BETWEEN :start AND :end
        ORDER BY trading_day, category_name
    """, {"start": start, "end": end})


# ============================================================================
# HOURLY SALES
# ============================================================================


def get_hourly_sales(trading_day: date) -> pd.DataFrame:
    """Get hourly sales breakdown for a specific trading day."""
    return _q("""
        SELECT hour_of_day, net_sales, gross_sales, check_count,
               guest_count, avg_check, tips
        FROM pos_hourly_sales
        WHERE trading_day = :day
        ORDER BY hour_of_day
    """, {"day": trading_day})


def get_hourly_heatmap_data(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Get hourly data aggregated by day-of-week for heatmap.
    Returns avg net_sales, avg check_count, avg guest_count per (dow, hour).
    """
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            EXTRACT(DOW FROM trading_day)::int AS dow,
            TO_CHAR(trading_day, 'Dy') AS dow_name,
            hour_of_day,
            AVG(net_sales) AS avg_net_sales,
            AVG(check_count) AS avg_checks,
            AVG(guest_count) AS avg_guests,
            SUM(net_sales) AS total_net_sales,
            SUM(check_count) AS total_checks,
            COUNT(*) AS num_days
        FROM pos_hourly_sales
        {where}
        GROUP BY EXTRACT(DOW FROM trading_day), TO_CHAR(trading_day, 'Dy'), hour_of_day
        ORDER BY dow, hour_of_day
    """, params)


def get_hourly_trend(start: date, end: date) -> pd.DataFrame:
    """Get raw hourly data over a date range for trend analysis."""
    return _q("""
        SELECT trading_day, hour_of_day, net_sales, check_count, guest_count, tips
        FROM pos_hourly_sales
        WHERE trading_day BETWEEN :start AND :end
        ORDER BY trading_day, hour_of_day
    """, {"start": start, "end": end})


def get_daily_labor(start: date = None, end: date = None) -> pd.DataFrame:
    """Get labor hours and cost aggregated by trading day."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND s.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND s.trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            s.trading_day,
            COALESCE(l.shift_count, 0) AS shift_count,
            COALESCE(l.total_hours, 0) AS total_hours,
            COALESCE(l.pos_labor_cost, 0) AS pos_labor_cost,
            {_fixed_labor_for_day_expr("s.trading_day")} AS fixed_labor_cost,
            COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")} AS wages_cost,
            ROUND(
                (COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")})
                * {_payroll_tax_rate_for_day_expr("s.trading_day")},
                2
            ) AS payroll_tax,
            ROUND({_payroll_fee_daily_for_day_expr("s.trading_day")}, 2) AS payroll_fee_daily,
            COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")}
                + (COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")})
                  * {_payroll_tax_rate_for_day_expr("s.trading_day")}
                + {_payroll_fee_daily_for_day_expr("s.trading_day")}
            AS total_labor_cost,
            COALESCE(l.total_tips, 0) AS total_tips
        FROM pos_daily_sales s
        LEFT JOIN (
            SELECT
                trading_day,
                COUNT(*) AS shift_count,
                SUM(reg_hours + COALESCE(ot_hours, 0)) AS total_hours,
                SUM(total_pay) AS pos_labor_cost,
                SUM(total_tips) AS total_tips
            FROM {_trusted_labor_subquery("l")}
            GROUP BY trading_day
        ) l ON s.trading_day = l.trading_day
        {where}
        ORDER BY s.trading_day
    """, params)


def get_labor_by_role(trading_day: date) -> pd.DataFrame:
    """Get labor breakdown by role for a specific day."""
    return _q("""
        SELECT
            role,
            COUNT(*) AS shifts,
            SUM(reg_hours + COALESCE(ot_hours, 0)) AS total_hours,
            SUM(total_pay) AS total_cost
        FROM (
            SELECT pl.*
            FROM pos_labor pl
            JOIN import_logs il ON il.id = pl.import_log_id
            WHERE il.import_type = 'labor'
              AND il.status = 'success'
        ) l
        WHERE trading_day = :day
        GROUP BY role
        ORDER BY total_hours DESC
    """, {"day": trading_day})


def get_hourly_labor(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Estimate labor hours by hour-of-day from shift data.
    This approximates staff-on-floor per hour.
    """
    where = "WHERE shift_start IS NOT NULL AND shift_end IS NOT NULL"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT trading_day, shift_start, shift_end, role,
               EXTRACT(HOUR FROM shift_start)::int AS start_hour,
               EXTRACT(HOUR FROM shift_end)::int AS end_hour
        FROM {_trusted_labor_subquery("l")}
        {where}
        ORDER BY trading_day, shift_start
    """, params)


# ============================================================================
# COMPS & VOIDS
# ============================================================================


def get_comps(start: date = None, end: date = None) -> pd.DataFrame:
    """Get all comp records, optionally filtered by date range."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT id, comp_date, comp_reason, check_owner, authorized_by,
               check_number, comp_type, item_name, amount, note, trading_day
        FROM pos_comps
        {where}
        ORDER BY comp_date DESC
    """, params)


def get_comp_summary(start: date = None, end: date = None) -> pd.DataFrame:
    """Get comp totals by reason."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            comp_reason,
            COUNT(*) AS comp_count,
            SUM(amount) AS total_amount,
            AVG(amount) AS avg_amount
        FROM pos_comps
        {where}
        GROUP BY comp_reason
        ORDER BY total_amount DESC
    """, params)


def get_comp_daily_trend(start: date = None, end: date = None) -> pd.DataFrame:
    """Get daily comp totals."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            trading_day,
            COUNT(*) AS comp_count,
            SUM(amount) AS total_amount
        FROM pos_comps
        {where}
        GROUP BY trading_day
        ORDER BY trading_day
    """, params)


def get_comp_by_employee(start: date = None, end: date = None) -> pd.DataFrame:
    """Get comp totals by authorizing employee."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            authorized_by,
            COUNT(*) AS comp_count,
            SUM(amount) AS total_amount
        FROM pos_comps
        {where}
        GROUP BY authorized_by
        ORDER BY total_amount DESC
    """, params)


def get_voids(start: date = None, end: date = None) -> pd.DataFrame:
    """Get all void records, optionally filtered by date range."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT id, void_date, void_reason, check_owner, authorized_by,
               check_number, item_name, amount, note, trading_day
        FROM pos_voids
        {where}
        ORDER BY void_date DESC
    """, params)


def get_void_summary(start: date = None, end: date = None) -> pd.DataFrame:
    """Get void totals by reason."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            void_reason,
            COUNT(*) AS void_count,
            SUM(amount) AS total_amount,
            AVG(amount) AS avg_amount
        FROM pos_voids
        {where}
        GROUP BY void_reason
        ORDER BY total_amount DESC
    """, params)


def get_void_daily_trend(start: date = None, end: date = None) -> pd.DataFrame:
    """Get daily void totals."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            trading_day,
            COUNT(*) AS void_count,
            SUM(amount) AS total_amount
        FROM pos_voids
        {where}
        GROUP BY trading_day
        ORDER BY trading_day
    """, params)


# ============================================================================
# COMPS & VOIDS -- TRUE COST (COGS) VARIANTS
# ============================================================================


def _comp_cost_where(start: date = None, end: date = None):
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND c.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND c.trading_day <= :end"
        params["end"] = end
    return where, params


def get_comps_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """All comp records with per-serving COGS from pos_items."""
    where, params = _comp_cost_where(start, end)
    return _q(f"""
        SELECT c.id, c.comp_date, c.comp_reason, c.check_owner, c.authorized_by,
               c.check_number, c.comp_type, c.item_name, c.amount, c.note,
               c.trading_day,
               pi.cost AS true_cost,
               CASE WHEN pi.cost IS NOT NULL AND pi.cost > 0 THEN 1 ELSE 0 END AS has_cost
        FROM pos_comps c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        ORDER BY c.comp_date DESC
    """, params)


def get_comp_summary_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """Comp totals by reason with both menu-price and COGS amounts."""
    where, params = _comp_cost_where(start, end)
    return _q(f"""
        SELECT
            c.comp_reason,
            COUNT(*) AS comp_count,
            SUM(c.amount) AS total_amount,
            AVG(c.amount) AS avg_amount,
            COALESCE(SUM(pi.cost), 0) AS total_true_cost,
            SUM(CASE WHEN pi.cost IS NOT NULL AND pi.cost > 0 THEN 1 ELSE 0 END) AS items_with_cost
        FROM pos_comps c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        GROUP BY c.comp_reason
        ORDER BY total_amount DESC
    """, params)


def get_comp_daily_trend_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """Daily comp totals with both menu-price and COGS amounts."""
    where, params = _comp_cost_where(start, end)
    return _q(f"""
        SELECT
            c.trading_day,
            COUNT(*) AS comp_count,
            SUM(c.amount) AS total_amount,
            COALESCE(SUM(pi.cost), 0) AS total_true_cost
        FROM pos_comps c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        GROUP BY c.trading_day
        ORDER BY c.trading_day
    """, params)


def get_comp_by_employee_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """Comp totals by authorizing employee with both menu-price and COGS amounts."""
    where, params = _comp_cost_where(start, end)
    return _q(f"""
        SELECT
            c.authorized_by,
            COUNT(*) AS comp_count,
            SUM(c.amount) AS total_amount,
            COALESCE(SUM(pi.cost), 0) AS total_true_cost
        FROM pos_comps c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        GROUP BY c.authorized_by
        ORDER BY total_amount DESC
    """, params)


def get_voids_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """All void records with per-serving COGS from pos_items."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND c.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND c.trading_day <= :end"
        params["end"] = end
    return _q(f"""
        SELECT c.id, c.void_date, c.void_reason, c.check_owner, c.authorized_by,
               c.check_number, c.item_name, c.amount, c.note,
               c.trading_day,
               pi.cost AS true_cost,
               CASE WHEN pi.cost IS NOT NULL AND pi.cost > 0 THEN 1 ELSE 0 END AS has_cost
        FROM pos_voids c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        ORDER BY c.void_date DESC
    """, params)


def get_void_summary_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """Void totals by reason with both menu-price and COGS amounts."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND c.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND c.trading_day <= :end"
        params["end"] = end
    return _q(f"""
        SELECT
            c.void_reason,
            COUNT(*) AS void_count,
            SUM(c.amount) AS total_amount,
            AVG(c.amount) AS avg_amount,
            COALESCE(SUM(pi.cost), 0) AS total_true_cost,
            SUM(CASE WHEN pi.cost IS NOT NULL AND pi.cost > 0 THEN 1 ELSE 0 END) AS items_with_cost
        FROM pos_voids c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        GROUP BY c.void_reason
        ORDER BY total_amount DESC
    """, params)


def get_void_daily_trend_with_cost(start: date = None, end: date = None) -> pd.DataFrame:
    """Daily void totals with both menu-price and COGS amounts."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND c.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND c.trading_day <= :end"
        params["end"] = end
    return _q(f"""
        SELECT
            c.trading_day,
            COUNT(*) AS void_count,
            SUM(c.amount) AS total_amount,
            COALESCE(SUM(pi.cost), 0) AS total_true_cost
        FROM pos_voids c
        LEFT JOIN pos_items pi ON LOWER(TRIM(c.item_name)) = LOWER(TRIM(pi.name))
        {where}
        GROUP BY c.trading_day
        ORDER BY c.trading_day
    """, params)


# ============================================================================
# PRODUCT MIX
# ============================================================================


def get_top_sellers(trading_day: date = None, start: date = None,
                    end: date = None, limit: int = 20) -> pd.DataFrame:
    """Get top selling items by quantity for a date or range."""
    where = "WHERE entry_type = 'Item'"
    params = {"limit": limit}

    if trading_day:
        where += " AND report_start_date = :day AND report_end_date = :day"
        params["day"] = trading_day
    elif start and end:
        where += " AND report_start_date >= :start AND report_end_date <= :end"
        params["start"] = start
        params["end"] = end

    return _q(f"""
        SELECT item_name, category_name,
               SUM(qty_sold) AS total_sold,
               SUM(net_sales) AS total_revenue,
               AVG(avg_price) AS avg_price
        FROM pos_product_mix
        {where}
        GROUP BY item_name, category_name
        ORDER BY total_sold DESC
        LIMIT :limit
    """, params)


# ============================================================================
# VENDORS
# ============================================================================


def get_vendors() -> pd.DataFrame:
    """Get all vendors."""
    return _q("""
        SELECT id, name, contact_name, email, phone,
               supply_categories, delivery_days,
               order_deadline_day, order_deadline_time,
               lead_time_days, invoice_format, notes
        FROM inv_vendors
        ORDER BY name
    """)


def get_vendor_names() -> list[str]:
    """Get vendor names for dropdown."""
    df = _q("SELECT name FROM inv_vendors ORDER BY name")
    return df["name"].tolist() if not df.empty else []


def get_vendor_id_by_name(name: str) -> int | None:
    """Look up vendor ID by name."""
    df = _q("SELECT id FROM inv_vendors WHERE name = :name", {"name": name})
    return int(df.iloc[0]["id"]) if not df.empty else None


# ============================================================================
# INVENTORY ITEMS
# ============================================================================


def get_inv_items() -> pd.DataFrame:
    """
    Get all active inventory items with pour economics derived in SQL.

    Derived columns (not stored, calculated from base fields):
      bottle_size_oz    = bottle_size_ml / 29.5735
      pours_per_unit    = bottle_size_oz / standard_pour_oz
      cost_per_pour     = unit_cost / pours_per_unit
      pour_cost_pct     = cost_per_pour / menu_price * 100
      revenue_per_unit  = menu_price * pours_per_unit
    """
    return _q("""
        SELECT i.id, i.name, i.category, i.subcategory,
               i.unit_of_measure, i.pack_size, i.bottle_size_ml,
               i.par_level, i.reorder_point, i.reorder_qty, i.inventory_tier,
               i.unit_cost, i.case_cost, i.status,
               i.purchase_unit, i.current_qty, i.standard_pour_oz, i.menu_price,
               i.pos_item_id, i.notes,
               v.name AS vendor_name,
               i.primary_vendor_id,
               ROUND(CAST(i.bottle_size_ml AS NUMERIC) / 29.5735, 1) AS bottle_size_oz,
               CASE
                   WHEN i.standard_pour_oz > 0 AND i.bottle_size_ml > 0
                   THEN ROUND((CAST(i.bottle_size_ml AS NUMERIC) / 29.5735) / i.standard_pour_oz, 0)
                   ELSE NULL
               END AS pours_per_unit,
               CASE
                   WHEN i.standard_pour_oz > 0 AND i.bottle_size_ml > 0 AND i.unit_cost > 0
                   THEN ROUND(
                       i.unit_cost / ((CAST(i.bottle_size_ml AS NUMERIC) / 29.5735) / i.standard_pour_oz),
                       2)
                   ELSE NULL
               END AS cost_per_pour,
               CASE
                   WHEN i.menu_price > 0 AND i.standard_pour_oz > 0
                        AND i.bottle_size_ml > 0 AND i.unit_cost > 0
                   THEN ROUND(
                       (i.unit_cost / ((CAST(i.bottle_size_ml AS NUMERIC) / 29.5735) / i.standard_pour_oz))
                       / i.menu_price * 100,
                       1)
                   ELSE NULL
               END AS pour_cost_pct,
               CASE
                   WHEN i.menu_price > 0 AND i.standard_pour_oz > 0 AND i.bottle_size_ml > 0
                   THEN ROUND(
                       i.menu_price * ((CAST(i.bottle_size_ml AS NUMERIC) / 29.5735) / i.standard_pour_oz),
                       2)
                   ELSE NULL
               END AS revenue_per_unit
        FROM inv_items i
        LEFT JOIN inv_vendors v ON i.primary_vendor_id = v.id
        WHERE i.status = 'active'
        ORDER BY i.name
    """)


def get_inv_item_names() -> list[str]:
    """Get inventory item names for autocomplete."""
    df = _q("SELECT name FROM inv_items WHERE status = 'active' ORDER BY name")
    return df["name"].tolist() if not df.empty else []


def get_item_purchase_history(item_id: int) -> pd.DataFrame:
    """
    Get invoice lines matched to a specific inventory item, most recent first.
    Used in the Edit Item tab to show cost history from vendor invoices.
    """
    return _q("""
        SELECT
            inv.invoice_date,
            inv.invoice_number,
            v.name AS vendor_name,
            il.quantity,
            il.unit_of_measure,
            il.unit_price,
            il.extended_price,
            il.description
        FROM inv_invoice_lines il
        JOIN inv_invoices inv ON il.invoice_id = inv.id
        LEFT JOIN inv_vendors v ON inv.vendor_id = v.id
        WHERE il.inv_item_id = :item_id
          AND il.line_type = 'item'
        ORDER BY inv.invoice_date DESC
        LIMIT 20
    """, {"item_id": item_id})


def get_pos_items_for_linking() -> pd.DataFrame:
    """
    Get POS menu items for the inv_item <-> pos_item linking dropdown.
    Returns id, name, category, price, and cost so the user can confirm
    they're linking to the right item.
    """
    return _q("""
        SELECT id, name, category_name, price, cost
        FROM pos_items
        WHERE status = 'Active' OR status IS NULL
        ORDER BY category_name, name
    """)


def update_inv_item(item_id: int, fields: dict) -> None:
    """
    Update arbitrary fields on an inv_item row by ID.
    Only updates keys present in `fields`; ignores unknown keys.
    Always sets updated_at to now.
    """
    from src.config import get_session
    from src.models import InvItem
    from datetime import datetime

    allowed = {
        "name", "category", "subcategory", "unit_of_measure", "pack_size",
        "bottle_size_ml", "par_level", "reorder_point", "reorder_qty",
        "inventory_tier", "primary_vendor_id", "unit_cost", "case_cost",
        "purchase_unit", "current_qty", "standard_pour_oz", "menu_price",
        "pos_item_id", "status", "notes",
    }
    session = get_session()
    try:
        item = session.query(InvItem).filter(InvItem.id == item_id).first()
        if item is None:
            raise ValueError(f"No inv_item with id={item_id}")
        for key, value in fields.items():
            if key in allowed:
                setattr(item, key, value)
        item.updated_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()


# ============================================================================
# INVOICES
# ============================================================================


def get_invoices(start: date = None, end: date = None) -> pd.DataFrame:
    """Get all invoices with vendor info."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND i.invoice_date >= :start"
        params["start"] = start
    if end:
        where += " AND i.invoice_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT i.id, i.vendor_id, i.invoice_number, i.invoice_date,
               i.received_date, i.total_amount, i.status, i.notes,
               i.source_file,
               v.name AS vendor_name,
               COUNT(l.id) AS line_count
        FROM inv_invoices i
        LEFT JOIN inv_vendors v ON i.vendor_id = v.id
        LEFT JOIN inv_invoice_lines l ON l.invoice_id = i.id
        {where}
        GROUP BY i.id, i.vendor_id, i.invoice_number, i.invoice_date,
                 i.received_date, i.total_amount, i.status, i.notes,
                 i.source_file, v.name
        ORDER BY i.invoice_date DESC
    """, params)


def get_invoice_lines(invoice_id: int) -> pd.DataFrame:
    """Get line items for a specific invoice."""
    return _q("""
        SELECT l.id, l.line_number, l.description, l.quantity,
               l.unit_of_measure, l.unit_price, l.extended_price,
               l.line_type, l.matched, ii.name AS inv_item_name
        FROM inv_invoice_lines l
        LEFT JOIN inv_items ii ON l.inv_item_id = ii.id
        WHERE l.invoice_id = :invoice_id
        ORDER BY l.line_number
    """, {"invoice_id": invoice_id})


def get_invoice_totals() -> pd.DataFrame:
    """Get invoice spend summary by vendor."""
    return _q("""
        SELECT
            v.name AS vendor_name,
            COUNT(DISTINCT i.id) AS invoice_count,
            SUM(i.total_amount) AS total_spend,
            MIN(i.invoice_date) AS first_invoice,
            MAX(i.invoice_date) AS last_invoice
        FROM inv_invoices i
        JOIN inv_vendors v ON i.vendor_id = v.id
        GROUP BY v.name
        ORDER BY total_spend DESC
    """)


# ============================================================================
# RECIPES
# ============================================================================


def get_recipes() -> pd.DataFrame:
    """Get all recipes with POS item info."""
    return _q("""
        SELECT r.id, r.recipe_name, r.pos_item_id, r.version,
               r.yield_qty, r.status, r.notes,
               p.name AS pos_item_name, p.category_name,
               COUNT(rl.id) AS ingredient_count
        FROM recipes r
        LEFT JOIN pos_items p ON r.pos_item_id = p.id
        LEFT JOIN recipe_lines rl ON rl.recipe_id = r.id
        GROUP BY r.id, r.recipe_name, r.pos_item_id, r.version,
                 r.yield_qty, r.status, r.notes,
                 p.name, p.category_name
        ORDER BY r.recipe_name
    """)


def get_recipe_lines(recipe_id: int) -> pd.DataFrame:
    """Get ingredient lines for a specific recipe."""
    return _q("""
        SELECT rl.id, rl.quantity, rl.unit_of_measure,
               rl.waste_factor, rl.notes,
               ii.name AS ingredient_name, ii.category AS ingredient_category
        FROM recipe_lines rl
        JOIN inv_items ii ON rl.inv_item_id = ii.id
        WHERE rl.recipe_id = :recipe_id
        ORDER BY ii.name
    """, {"recipe_id": recipe_id})


def get_pos_items_for_recipes() -> pd.DataFrame:
    """Get POS items that could have recipes (mainly cocktails, food)."""
    return _q("""
        SELECT id, name, category_name, price
        FROM pos_items
        WHERE status = 'Active'
        ORDER BY category_name, name
    """)


# ============================================================================
# INVENTORY LEDGER
# ============================================================================


def get_ledger_current(as_of: date = None) -> pd.DataFrame:
    """Get the latest ledger snapshot for all tracked items."""
    params = {}
    date_filter = ""
    if as_of:
        date_filter = "AND l.ledger_date = :as_of"
        params["as_of"] = as_of
    else:
        date_filter = "AND l.ledger_date = (SELECT MAX(ledger_date) FROM inv_daily_ledger)"

    return _q(f"""
        SELECT
            l.ledger_date,
            i.id AS inv_item_id,
            i.name AS item_name,
            i.category,
            i.subcategory,
            i.unit_of_measure,
            i.par_level,
            i.reorder_point,
            l.opening_qty,
            l.purchases_qty,
            l.theoretical_usage,
            l.adjustments_qty,
            l.closing_qty,
            l.days_of_cover,
            l.reorder_alert,
            v.name AS vendor_name
        FROM inv_daily_ledger l
        JOIN inv_items i ON l.inv_item_id = i.id
        LEFT JOIN inv_vendors v ON i.primary_vendor_id = v.id
        WHERE i.status = 'active'
          {date_filter}
        ORDER BY l.reorder_alert DESC, i.name
    """, params)


def get_ledger_history(inv_item_id: int, days: int = 30) -> pd.DataFrame:
    """Get ledger history for a single item over N days."""
    return _q("""
        SELECT ledger_date, opening_qty, purchases_qty,
               theoretical_usage, adjustments_qty, closing_qty,
               days_of_cover, reorder_alert
        FROM inv_daily_ledger
        WHERE inv_item_id = :item_id
        ORDER BY ledger_date DESC
        LIMIT :days
    """, {"item_id": inv_item_id, "days": days})


# ============================================================================
# PROFITABILITY & COST ANALYSIS
# ============================================================================


def get_prime_cost_data(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Get daily revenue, labor cost, and COGS data for prime cost analysis.
    Joins daily_sales with labor totals.
    """
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND s.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND s.trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            s.trading_day,
            s.net_sales,
            s.gross_sales,
            s.total_comps,
            s.total_voids,
            s.total_guests,
            s.total_checks,
            s.guest_avg,
            s.check_avg,
            COALESCE(l.pos_labor_cost, 0) AS pos_labor_cost,
            {_fixed_labor_for_day_expr("s.trading_day")} AS fixed_labor_cost,
            COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")} AS wages_cost,
            COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")}
                + (COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")})
                  * {_payroll_tax_rate_for_day_expr("s.trading_day")}
                + {_payroll_fee_daily_for_day_expr("s.trading_day")}
            AS labor_cost,
            COALESCE(l.total_hours, 0) AS labor_hours,
            COALESCE(l.shift_count, 0) AS shift_count
        FROM pos_daily_sales s
        LEFT JOIN (
            SELECT
                trading_day,
                SUM(total_pay) AS pos_labor_cost,
                SUM(reg_hours + COALESCE(ot_hours, 0)) AS total_hours,
                COUNT(*) AS shift_count
            FROM {_trusted_labor_subquery("l")}
            GROUP BY trading_day
        ) l ON s.trading_day = l.trading_day
        {where}
        ORDER BY s.trading_day
    """, params)


def get_category_profitability(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Get category-level profitability: revenue, cost, gross profit.
    Uses product mix data which has cost info per item.
    """
    where = "WHERE entry_type = 'Item'"
    params = {}
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            category_name,
            SUM(qty_sold) AS total_qty,
            SUM(gross_sales) AS gross_revenue,
            SUM(net_sales) AS net_revenue,
            SUM(cost) AS total_cost,
            SUM(gross_profit) AS gross_profit,
            SUM(comp_amount) AS total_comps,
            COUNT(DISTINCT item_name) AS unique_items
        FROM pos_product_mix
        {where}
        GROUP BY category_name
        ORDER BY net_revenue DESC
    """, params)


def get_pour_cost_by_category(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Get pour cost (cost / revenue) by category.
    Only meaningful for categories with cost data populated.
    """
    where = "WHERE entry_type = 'Item' AND cost > 0"
    params = {}
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            category_name,
            SUM(net_sales) AS net_revenue,
            SUM(cost) AS total_cost,
            CASE WHEN SUM(net_sales) > 0
                 THEN ROUND(SUM(cost) / SUM(net_sales) * 100, 1)
                 ELSE 0 END AS pour_cost_pct
        FROM pos_product_mix
        {where}
        GROUP BY category_name
        HAVING SUM(net_sales) > 0
        ORDER BY pour_cost_pct DESC
    """, params)


def get_splh_trend(start: date = None, end: date = None) -> pd.DataFrame:
    """Get Sales Per Labor Hour trend by day."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND s.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND s.trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            s.trading_day,
            s.net_sales,
            l.total_hours,
            COALESCE(l.pos_labor_cost, 0) AS pos_labor_cost,
            {_fixed_labor_for_day_expr("s.trading_day")} AS fixed_labor_cost,
            COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")} AS wages_cost,
            COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")}
                + (COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")})
                  * {_payroll_tax_rate_for_day_expr("s.trading_day")}
                + {_payroll_fee_daily_for_day_expr("s.trading_day")}
            AS total_labor_cost,
            CASE WHEN l.total_hours > 0
                 THEN ROUND(s.net_sales / l.total_hours, 2)
                 ELSE NULL END AS splh,
            CASE WHEN s.net_sales > 0
                 THEN ROUND(
                    (
                        COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")}
                        + (COALESCE(l.pos_labor_cost, 0) + {_fixed_labor_for_day_expr("s.trading_day")})
                          * {_payroll_tax_rate_for_day_expr("s.trading_day")}
                        + {_payroll_fee_daily_for_day_expr("s.trading_day")}
                    )
                    / s.net_sales * 100,
                    1
                 )
                 ELSE NULL END AS labor_pct
        FROM pos_daily_sales s
        LEFT JOIN (
            SELECT
                trading_day,
                SUM(reg_hours + COALESCE(ot_hours, 0)) AS total_hours,
                SUM(total_pay) AS pos_labor_cost
            FROM {_trusted_labor_subquery("l")}
            GROUP BY trading_day
        ) l ON s.trading_day = l.trading_day
        {where}
        ORDER BY s.trading_day
    """, params)


def get_untrusted_labor_rows(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Return labor rows not tied to successful Lightspeed labor imports.
    Useful for surfacing data quality issues that are excluded from labor KPIs.
    """
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND l.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND l.trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            l.trading_day,
            COUNT(*) AS row_count,
            COALESCE(SUM(l.total_pay), 0) AS total_pay
        FROM pos_labor l
        LEFT JOIN import_logs il ON il.id = l.import_log_id
        {where}
          AND (
              il.id IS NULL
              OR il.import_type <> 'labor'
              OR il.status <> 'success'
          )
        GROUP BY l.trading_day
        ORDER BY l.trading_day
    """, params)


def get_untrusted_labor_details(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Return row-level labor records excluded from KPI calculations, with import metadata.
    """
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND l.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND l.trading_day <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            l.trading_day,
            COALESCE(l.employee_id, '') AS employee_id,
            TRIM(l.first_name) AS first_name,
            TRIM(l.last_name) AS last_name,
            l.role,
            l.shift_start,
            l.shift_end,
            l.reg_hours,
            l.ot_hours,
            l.total_pay,
            l.import_log_id,
            il.filename AS import_filename,
            il.import_type,
            il.status AS import_status
        FROM pos_labor l
        LEFT JOIN import_logs il ON il.id = l.import_log_id
        {where}
          AND (
              il.id IS NULL
              OR il.import_type <> 'labor'
              OR il.status <> 'success'
          )
        ORDER BY l.trading_day, l.last_name, l.first_name, l.shift_start
    """, params)


# ============================================================================
# PRODUCT MIX & MENU ENGINEERING
# ============================================================================


def get_full_product_mix(start: date = None, end: date = None) -> pd.DataFrame:
    """Get all product mix items with full detail for menu engineering."""
    where = "WHERE entry_type = 'Item'"
    params = {}
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            item_name,
            category_name,
            SUM(qty_sold) AS total_sold,
            SUM(qty_void) AS total_voided,
            SUM(qty_comp) AS total_comped,
            SUM(gross_sales) AS gross_revenue,
            SUM(net_sales) AS net_revenue,
            SUM(cost) AS total_cost,
            SUM(gross_profit) AS gross_profit,
            SUM(comp_amount) AS comp_amount,
            AVG(avg_price) AS avg_price,
            CASE WHEN SUM(qty_sold) > 0
                 THEN ROUND(SUM(net_sales)::numeric / SUM(qty_sold), 2)
                 ELSE 0 END AS revenue_per_unit,
            CASE WHEN SUM(qty_sold) > 0 AND SUM(cost) > 0
                 THEN ROUND((SUM(net_sales) - SUM(cost))::numeric / SUM(qty_sold), 2)
                 ELSE NULL END AS margin_per_unit,
            CASE WHEN SUM(net_sales) > 0 AND SUM(cost) > 0
                 THEN ROUND(SUM(cost)::numeric / SUM(net_sales) * 100, 1)
                 ELSE NULL END AS cost_pct
        FROM pos_product_mix
        {where}
        GROUP BY item_name, category_name
        HAVING SUM(qty_sold) > 0
        ORDER BY SUM(net_sales) DESC
    """, params)


def get_product_mix_trend(item_name: str, start: date = None,
                          end: date = None) -> pd.DataFrame:
    """Get daily sales trend for a specific menu item."""
    where = "WHERE entry_type = 'Item' AND item_name = :item_name"
    params = {"item_name": item_name}
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            report_start_date AS trading_day,
            qty_sold, net_sales, cost, gross_profit
        FROM pos_product_mix
        {where}
          AND report_start_date = report_end_date
        ORDER BY report_start_date
    """, params)


def get_category_mix_summary(start: date = None, end: date = None) -> pd.DataFrame:
    """Get category-level product mix summary."""
    where = "WHERE entry_type = 'Category'"
    params = {}
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            item_name AS category_name,
            SUM(qty_sold) AS total_sold,
            SUM(net_sales) AS net_revenue,
            SUM(cost) AS total_cost,
            SUM(gross_profit) AS gross_profit
        FROM pos_product_mix
        {where}
        GROUP BY item_name
        ORDER BY SUM(net_sales) DESC
    """, params)


# ============================================================================
# OPERATIONAL EXPENSES
# ============================================================================


def get_expense_categories() -> pd.DataFrame:
    """Get all expense categories."""
    return _q("""
        SELECT id, name, expense_type, description, typical_frequency,
               is_fixed, budget_amount, status, notes
        FROM op_expense_categories
        ORDER BY expense_type, name
    """)


def get_active_expense_categories() -> pd.DataFrame:
    """Get active expense categories for dropdowns."""
    return _q("""
        SELECT id, name, expense_type, typical_frequency, is_fixed, budget_amount
        FROM op_expense_categories
        WHERE status = 'active'
        ORDER BY expense_type, name
    """)


def get_expense_category_names() -> list[str]:
    """Get expense category names for dropdown."""
    df = _q("""
        SELECT name FROM op_expense_categories
        WHERE status = 'active'
        ORDER BY name
    """)
    return df["name"].tolist() if not df.empty else []


def get_expenses(start: date = None, end: date = None) -> pd.DataFrame:
    """Get all expenses with category info, optionally filtered by date."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND e.expense_date >= :start"
        params["start"] = start
    if end:
        where += " AND e.expense_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT e.id, e.expense_date, e.period_start, e.period_end,
               e.amount, e.payment_method, e.reference_number, e.notes,
               e.recurring_expense_id,
               c.name AS category_name, c.expense_type
        FROM op_expenses e
        JOIN op_expense_categories c ON e.expense_category_id = c.id
        {where}
        ORDER BY e.expense_date DESC
    """, params)


def get_expenses_by_type(start: date = None, end: date = None) -> pd.DataFrame:
    """Get expense totals grouped by expense_type for P&L rollup."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND e.expense_date >= :start"
        params["start"] = start
    if end:
        where += " AND e.expense_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            c.expense_type,
            SUM(e.amount) AS total_amount,
            COUNT(*) AS entry_count
        FROM op_expenses e
        JOIN op_expense_categories c ON e.expense_category_id = c.id
        {where}
        GROUP BY c.expense_type
        ORDER BY total_amount DESC
    """, params)


def get_expenses_by_category(start: date = None, end: date = None) -> pd.DataFrame:
    """Get expense totals grouped by individual category."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND e.expense_date >= :start"
        params["start"] = start
    if end:
        where += " AND e.expense_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            c.name AS category_name,
            c.expense_type,
            c.budget_amount,
            SUM(e.amount) AS total_amount,
            COUNT(*) AS entry_count
        FROM op_expense_categories c
        LEFT JOIN op_expenses e ON e.expense_category_id = c.id
            AND 1=1 {where.replace("WHERE 1=1 AND", "AND").replace("WHERE 1=1", "")}
        WHERE c.status = 'active'
        GROUP BY c.name, c.expense_type, c.budget_amount
        ORDER BY c.expense_type, c.name
    """, params)


def get_monthly_expenses(months: int = 12) -> pd.DataFrame:
    """Get expenses aggregated by month and type for trend analysis."""
    return _q("""
        SELECT
            DATE_TRUNC('month', e.expense_date)::date AS month,
            c.expense_type,
            SUM(e.amount) AS total_amount
        FROM op_expenses e
        JOIN op_expense_categories c ON e.expense_category_id = c.id
        WHERE e.expense_date >= (CURRENT_DATE - INTERVAL ':months months')
        GROUP BY DATE_TRUNC('month', e.expense_date), c.expense_type
        ORDER BY month, c.expense_type
    """, {"months": months})


def get_opex_total(start: date = None, end: date = None) -> float:
    """Get total operating expenses for a period (for P&L)."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND expense_date >= :start"
        params["start"] = start
    if end:
        where += " AND expense_date <= :end"
        params["end"] = end

    df = _q(f"""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM op_expenses
        {where}
    """, params)
    return float(df.iloc[0]["total"]) if not df.empty else 0.0


# ============================================================================
# RECURRING EXPENSES
# ============================================================================


def get_recurring_expenses(active_only: bool = True) -> pd.DataFrame:
    """Get recurring expense templates with category info."""
    where = ""
    if active_only:
        where = "WHERE (r.end_date IS NULL OR r.end_date >= DATE_TRUNC('month', CURRENT_DATE))"

    return _q(f"""
        SELECT r.id, r.expense_category_id, r.amount, r.frequency,
               r.day_of_month, r.start_date, r.end_date,
               r.payment_method, r.notes, r.created_at,
               c.name AS category_name, c.expense_type
        FROM recurring_expenses r
        JOIN op_expense_categories c ON r.expense_category_id = c.id
        {where}
        ORDER BY c.name, r.start_date
    """)


def get_recurring_expense_stats() -> pd.DataFrame:
    """Get count of generated rows per recurring template."""
    return _q("""
        SELECT r.id AS recurring_id,
               COUNT(e.id) AS generated_count
        FROM recurring_expenses r
        LEFT JOIN op_expenses e ON e.recurring_expense_id = r.id
        GROUP BY r.id
    """)


def generate_recurring_expenses(recurring_id: int = None) -> int:
    """
    Generate op_expenses rows from recurring expense templates.
    Generates from each template's start_date through the current month.
    Uses INSERT ... ON CONFLICT-style idempotency via existence check.

    Args:
        recurring_id: If provided, only generate for this specific template.
                      If None, generate for all active templates.

    Returns:
        Number of new rows inserted.
    """
    import calendar

    # Load templates
    if recurring_id:
        templates = _q("""
            SELECT id, expense_category_id, amount, frequency, day_of_month,
                   start_date, end_date, payment_method, notes
            FROM recurring_expenses
            WHERE id = :rid
        """, {"rid": recurring_id})
    else:
        templates = _q("""
            SELECT id, expense_category_id, amount, frequency, day_of_month,
                   start_date, end_date, payment_method, notes
            FROM recurring_expenses
            WHERE end_date IS NULL
               OR end_date >= DATE_TRUNC('month', CURRENT_DATE)::date
        """)

    if templates.empty:
        return 0

    today = date.today()
    current_month_start = today.replace(day=1)
    total_inserted = 0

    with engine.begin() as conn:
        for _, tmpl in templates.iterrows():
            rid = int(tmpl["id"])
            cat_id = int(tmpl["expense_category_id"])
            amount = tmpl["amount"]
            freq = tmpl["frequency"]
            dom = int(tmpl["day_of_month"]) if tmpl["day_of_month"] else 1
            start = tmpl["start_date"]
            end = tmpl["end_date"]
            pm = tmpl["payment_method"]
            notes = tmpl["notes"]

            # Build list of period start dates
            periods = _compute_periods(start, end, freq, current_month_start)

            for period_start in periods:
                # Compute period_end
                if freq == "monthly":
                    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
                    period_end = period_start.replace(day=last_day)
                elif freq == "quarterly":
                    # End of quarter (3 months from start)
                    m = period_start.month + 2
                    y = period_start.year + (m - 1) // 12
                    m = ((m - 1) % 12) + 1
                    last_day = calendar.monthrange(y, m)[1]
                    period_end = date(y, m, last_day)
                elif freq == "annual":
                    # End of year from start month
                    m = period_start.month + 11
                    y = period_start.year + (m - 1) // 12
                    m = ((m - 1) % 12) + 1
                    last_day = calendar.monthrange(y, m)[1]
                    period_end = date(y, m, last_day)
                else:
                    period_end = period_start

                # Expense date: day_of_month within the period's first month
                safe_dom = min(dom, calendar.monthrange(period_start.year, period_start.month)[1])
                expense_date = period_start.replace(day=safe_dom)

                # Check if already exists
                existing = conn.execute(
                    text("""
                        SELECT 1 FROM op_expenses
                        WHERE recurring_expense_id = :rid
                          AND period_start = :ps
                        LIMIT 1
                    """),
                    {"rid": rid, "ps": period_start},
                ).fetchone()

                if existing is None:
                    conn.execute(
                        text("""
                            INSERT INTO op_expenses
                            (expense_category_id, recurring_expense_id, expense_date,
                             period_start, period_end, amount, payment_method, notes)
                            VALUES (:cat_id, :rid, :exp_date, :ps, :pe, :amt, :pm, :notes)
                        """),
                        {
                            "cat_id": cat_id,
                            "rid": rid,
                            "exp_date": expense_date,
                            "ps": period_start,
                            "pe": period_end,
                            "amt": amount,
                            "pm": pm,
                            "notes": f"[Recurring] {notes}" if notes else "[Recurring]",
                        },
                    )
                    total_inserted += 1

    return total_inserted


def _compute_periods(start: date, end, freq: str, current_month_start: date) -> list:
    """
    Compute list of period_start dates from start through current month.
    Respects end_date if set.
    """
    from dateutil.relativedelta import relativedelta

    if freq == "monthly":
        delta = relativedelta(months=1)
    elif freq == "quarterly":
        delta = relativedelta(months=3)
    elif freq == "annual":
        delta = relativedelta(years=1)
    else:
        delta = relativedelta(months=1)

    # Normalize start to 1st of month
    cursor = start.replace(day=1)
    cutoff = current_month_start

    # If end_date is set and before current month, use that as cutoff
    if end is not None and not pd.isna(end):
        end_month = end.replace(day=1) if hasattr(end, 'replace') else end
        if end_month < cutoff:
            cutoff = end_month

    periods = []
    while cursor <= cutoff:
        periods.append(cursor)
        cursor = cursor + delta

    return periods


def ensure_recurring_generated() -> int:
    """
    Lightweight check: ensure current month's recurring expenses exist.
    Called on dashboard page load. Returns count of newly generated rows.
    """
    today = date.today()
    current_month_start = today.replace(day=1)

    # Quick check: any active recurring templates missing current month rows?
    missing = _q("""
        SELECT r.id
        FROM recurring_expenses r
        WHERE (r.end_date IS NULL OR r.end_date >= :cms)
          AND r.start_date <= :cms
          AND NOT EXISTS (
              SELECT 1 FROM op_expenses e
              WHERE e.recurring_expense_id = r.id
                AND e.period_start = :cms
          )
    """, {"cms": current_month_start})

    if missing.empty:
        return 0

    # Generate all missing (not just current month -- catches any gaps)
    return generate_recurring_expenses()


def end_recurring_expense(recurring_id: int, end_date: date) -> int:
    """
    End a recurring expense template. Sets end_date and removes any
    generated rows for periods after end_date.

    Returns number of future rows deleted.
    """
    end_month_start = end_date.replace(day=1)

    with engine.begin() as conn:
        # Set end_date on template
        conn.execute(
            text("""
                UPDATE recurring_expenses
                SET end_date = :end_date, updated_at = NOW()
                WHERE id = :rid
            """),
            {"rid": recurring_id, "end_date": end_date},
        )

        # Delete generated rows for periods after end_date
        # (keep the end_date month itself)
        result = conn.execute(
            text("""
                DELETE FROM op_expenses
                WHERE recurring_expense_id = :rid
                  AND period_start > :end_month
            """),
            {"rid": recurring_id, "end_month": end_month_start},
        )
        return result.rowcount


# ============================================================================
# OWNER DISTRIBUTIONS (BELOW THE LINE)
# ============================================================================


def get_distributions(start: date = None, end: date = None) -> pd.DataFrame:
    """Get all owner/investor distributions."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND distribution_date >= :start"
        params["start"] = start
    if end:
        where += " AND distribution_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT id, distribution_date, recipient, amount,
               distribution_type, payment_method, reference_number, notes
        FROM owner_distributions
        {where}
        ORDER BY distribution_date DESC
    """, params)


def get_distributions_total(start: date = None, end: date = None) -> float:
    """Get total distributions for a period (below-the-line)."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND distribution_date >= :start"
        params["start"] = start
    if end:
        where += " AND distribution_date <= :end"
        params["end"] = end

    df = _q(f"""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM owner_distributions
        {where}
    """, params)
    return float(df.iloc[0]["total"]) if not df.empty else 0.0


# ============================================================================
# FULL P&L
# ============================================================================


def get_full_pnl(start: date = None, end: date = None) -> dict:
    """
    Compute full restaurant P&L for a given period.

    Returns dict with:
      net_sales, cogs, gross_profit, labor_cost, prime_cost_profit,
      opex_by_type, total_opex, net_operating_income,
      distributions, retained_cash
    """
    params = {}
    where_sales = "WHERE 1=1"
    where_labor = "WHERE 1=1"
    if start:
        where_sales += " AND trading_day >= :start"
        where_labor += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where_sales += " AND trading_day <= :end"
        where_labor += " AND trading_day <= :end"
        params["end"] = end

    # Revenue
    rev_df = _q(f"""
        SELECT COALESCE(SUM(net_sales), 0) AS net_sales,
               COALESCE(SUM(gross_sales), 0) AS gross_sales
        FROM pos_daily_sales {where_sales}
    """, params)
    net_sales = float(rev_df.iloc[0]["net_sales"])
    gross_sales = float(rev_df.iloc[0]["gross_sales"])

    # COGS (from product mix cost data)
    cogs_df = _q(f"""
        SELECT COALESCE(SUM(cost), 0) AS total_cogs
        FROM pos_product_mix
        WHERE entry_type = 'Item' AND cost > 0
          {"AND report_start_date >= :start" if start else ""}
          {"AND report_end_date <= :end" if end else ""}
    """, params)
    cogs = float(cogs_df.iloc[0]["total_cogs"])

    # Labor -- wages from POS clock-in data
    labor_df = _q(f"""
        SELECT COALESCE(SUM(total_pay), 0) AS labor_cost,
               COALESCE(SUM(reg_hours + COALESCE(ot_hours, 0)), 0) AS labor_hours
        FROM {_trusted_labor_subquery("l")} {where_labor}
    """, params)
    labor_cost_pos = float(labor_df.iloc[0]["labor_cost"])

    # Fixed daily labor costs and their burden.
    fixed_labor_df = _q(f"""
        WITH days AS (
            SELECT DISTINCT trading_day
            FROM pos_daily_sales
            {where_sales}
        )
        SELECT COALESCE(SUM(f.daily_amount), 0) AS fixed_labor_cost
        FROM days d
        JOIN labor_fixed_daily_costs f
          ON f.include_in_projections = TRUE
         AND d.trading_day >= f.effective_start_date
         AND (
                f.effective_end_date IS NULL
                OR d.trading_day <= f.effective_end_date
             )
    """, params)
    labor_cost_fixed = float(fixed_labor_df.iloc[0]["fixed_labor_cost"])
    labor_cost_wages = labor_cost_pos + labor_cost_fixed

    # Payroll burden: tax (% of wages) + flat monthly service fees
    burden_df = _q(f"""
        WITH days AS (
            SELECT DISTINCT trading_day
            FROM pos_daily_sales
            {where_sales}
        ),
        daily_wages AS (
            SELECT
                d.trading_day,
                COALESCE(pl.pos_wages, 0) AS pos_wages,
                COALESCE(fl.fixed_wages, 0) AS fixed_wages,
                COALESCE(pl.pos_wages, 0) + COALESCE(fl.fixed_wages, 0) AS total_wages
            FROM days d
            LEFT JOIN (
                SELECT trading_day, SUM(total_pay) AS pos_wages
                FROM {_trusted_labor_subquery("lw")}
                GROUP BY trading_day
            ) pl ON d.trading_day = pl.trading_day
            LEFT JOIN (
                SELECT d2.trading_day, SUM(f.daily_amount) AS fixed_wages
                FROM days d2
                JOIN labor_fixed_daily_costs f
                  ON f.include_in_projections = TRUE
                 AND d2.trading_day >= f.effective_start_date
                 AND (f.effective_end_date IS NULL OR d2.trading_day <= f.effective_end_date)
                GROUP BY d2.trading_day
            ) fl ON d.trading_day = fl.trading_day
        )
        SELECT
            COALESCE(SUM(
                dw.total_wages * pb.payroll_tax_rate
            ), 0) AS payroll_tax,
            COALESCE(SUM(
                pb.payroll_fee_monthly
                / CAST(DATE_PART('days',
                      DATE_TRUNC('month', dw.trading_day)
                      + INTERVAL '1 month'
                      - DATE_TRUNC('month', dw.trading_day)
                  ) AS NUMERIC)
            ), 0) AS payroll_fee
        FROM daily_wages dw
        JOIN payroll_burden_settings pb
          ON dw.trading_day >= pb.effective_start_date
         AND (pb.effective_end_date IS NULL OR dw.trading_day <= pb.effective_end_date)
    """, params)
    payroll_tax = float(burden_df.iloc[0]["payroll_tax"]) if not burden_df.empty else 0.0
    payroll_fee = float(burden_df.iloc[0]["payroll_fee"]) if not burden_df.empty else 0.0
    labor_cost = labor_cost_wages + payroll_tax + payroll_fee

    # Operating expenses by type
    opex_df = get_expenses_by_type(start, end)
    total_opex = float(opex_df["total_amount"].sum()) if not opex_df.empty else 0.0

    # Distributions
    total_distributions = get_distributions_total(start, end)

    # Compute P&L
    gross_profit = net_sales - cogs
    prime_cost_profit = gross_profit - labor_cost
    net_operating_income = prime_cost_profit - total_opex
    retained_cash = net_operating_income - total_distributions

    return {
        "gross_sales": gross_sales,
        "net_sales": net_sales,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": (gross_profit / net_sales * 100) if net_sales > 0 else 0,
        "labor_cost_pos": labor_cost_pos,
        "labor_cost_fixed": labor_cost_fixed,
        "labor_cost_wages": labor_cost_wages,
        "payroll_tax": payroll_tax,
        "payroll_fee": payroll_fee,
        "labor_cost": labor_cost,
        "labor_pct": (labor_cost / net_sales * 100) if net_sales > 0 else 0,
        "prime_cost": cogs + labor_cost,
        "prime_cost_pct": ((cogs + labor_cost) / net_sales * 100) if net_sales > 0 else 0,
        "prime_cost_profit": prime_cost_profit,
        "opex_by_type": opex_df.to_dict("records") if not opex_df.empty else [],
        "total_opex": total_opex,
        "opex_pct": (total_opex / net_sales * 100) if net_sales > 0 else 0,
        "net_operating_income": net_operating_income,
        "noi_pct": (net_operating_income / net_sales * 100) if net_sales > 0 else 0,
        "distributions": total_distributions,
        "retained_cash": retained_cash,
    }


def get_reorder_items() -> pd.DataFrame:
    """Get items currently flagged for reorder."""
    return _q("""
        SELECT
            i.name AS item_name,
            i.category,
            i.unit_of_measure,
            i.par_level,
            i.reorder_point,
            l.closing_qty,
            l.days_of_cover,
            l.ledger_date,
            v.name AS vendor_name,
            v.order_deadline_day,
            v.lead_time_days
        FROM inv_daily_ledger l
        JOIN inv_items i ON l.inv_item_id = i.id
        LEFT JOIN inv_vendors v ON i.primary_vendor_id = v.id
        WHERE l.reorder_alert = TRUE
          AND l.ledger_date = (SELECT MAX(ledger_date) FROM inv_daily_ledger)
        ORDER BY l.days_of_cover ASC NULLS FIRST
    """)


# ============================================================================
# PAYROLL (TIP POOL + WAGES)
# ============================================================================


def get_payroll_date_range() -> tuple[date, date]:
    """Min/max trading days from labor and sales for payroll date picker."""
    df = _q("""
        SELECT
            LEAST(
                COALESCE((SELECT MIN(trading_day) FROM (
                    SELECT pl.*
                    FROM pos_labor pl
                    JOIN import_logs il ON il.id = pl.import_log_id
                    WHERE il.import_type = 'labor'
                      AND il.status = 'success'
                ) l), CURRENT_DATE),
                COALESCE((SELECT MIN(trading_day) FROM pos_daily_sales), CURRENT_DATE)
            ) AS min_date,
            GREATEST(
                COALESCE((SELECT MAX(trading_day) FROM (
                    SELECT pl.*
                    FROM pos_labor pl
                    JOIN import_logs il ON il.id = pl.import_log_id
                    WHERE il.import_type = 'labor'
                      AND il.status = 'success'
                ) l), CURRENT_DATE),
                COALESCE((SELECT MAX(trading_day) FROM pos_daily_sales), CURRENT_DATE)
            ) AS max_date
    """)
    if df.empty:
        today = date.today()
        return today, today
    return df.iloc[0]["min_date"], df.iloc[0]["max_date"]


def get_payroll_settings() -> pd.DataFrame:
    """Single-row payroll config (kitchen_tipout_pct, barback_multiplier, food_category_name)."""
    return _q("""
        SELECT id, kitchen_tipout_pct, barback_multiplier, food_category_name
        FROM payroll_settings
        ORDER BY id
        LIMIT 1
    """)


def get_payroll_daily_inputs(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Per-day inputs for tip pool: credit_tips, net_food_sales, cash_tips, kitchen_tipout, foh_pool.
    Uses payroll_settings for food category and kitchen_tipout_pct.
    Driver is distinct trading days from pos_labor (so days with labor get a row even if no sales).
    """
    where_days = "WHERE 1=1"
    params = {}
    if start:
        where_days += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where_days += " AND trading_day <= :end"
        params["end"] = end

    return _q(f"""
        WITH settings AS (
            SELECT kitchen_tipout_pct, food_category_name
            FROM payroll_settings
            ORDER BY id
            LIMIT 1
        ),
        days AS (
            SELECT DISTINCT trading_day FROM {_trusted_labor_subquery("l")} {where_days}
        ),
        sales AS (
            SELECT trading_day, credit_tips FROM pos_daily_sales
        ),
        food AS (
            SELECT c.trading_day, COALESCE(SUM(c.net_sales), 0) AS net_food_sales
            FROM pos_daily_sales_by_category c
            CROSS JOIN settings s
            WHERE c.category_name = s.food_category_name
            GROUP BY c.trading_day
        ),
        cash AS (
            SELECT trading_day, COALESCE(amount, 0) AS cash_tips
            FROM payroll_cash_tips
        )
        SELECT
            d.trading_day,
            COALESCE(s.credit_tips, 0) AS credit_tips,
            COALESCE(f.net_food_sales, 0) AS net_food_sales,
            COALESCE(c.cash_tips, 0) AS cash_tips,
            (SELECT kitchen_tipout_pct FROM settings LIMIT 1) AS kitchen_tipout_pct,
            ROUND(
                COALESCE(f.net_food_sales, 0) * (SELECT kitchen_tipout_pct FROM settings LIMIT 1),
                2
            ) AS kitchen_tipout,
            ROUND(
                COALESCE(s.credit_tips, 0) + COALESCE(c.cash_tips, 0)
                - ROUND(
                    COALESCE(f.net_food_sales, 0) * (SELECT kitchen_tipout_pct FROM settings LIMIT 1),
                    2
                ),
                2
            ) AS foh_pool
        FROM days d
        LEFT JOIN sales s ON d.trading_day = s.trading_day
        LEFT JOIN food f ON d.trading_day = f.trading_day
        LEFT JOIN cash c ON d.trading_day = c.trading_day
        ORDER BY d.trading_day
    """, params)


def get_payroll_labor_with_multiplier(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Per-employee per-day labor: hours and effective tip_pool_multiplier.
    Joins pos_labor to payroll_employee_settings; defaults: Bartender=1.0, Bar Back=0.5, include only FOH roles.
    Employees not in settings get role-based default (Bartender 1.0, Bar Back 0.5) and include_in_tip_pool=true.
    """
    where = "AND l.role IN ('Bartender', 'Bar Back')"
    params = {}
    if start:
        where += " AND l.trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND l.trading_day <= :end"
        params["end"] = end

    return _q(f"""
        WITH settings AS (
            SELECT barback_multiplier
            FROM payroll_settings
            ORDER BY id
            LIMIT 1
        )
        SELECT
            l.trading_day,
            COALESCE(l.employee_id, '') AS employee_id,
            l.first_name,
            l.last_name,
            l.role,
            l.reg_hours,
            l.ot_hours,
            (l.reg_hours + COALESCE(l.ot_hours, 0)) AS total_hours,
            l.shift_start,
            l.shift_end,
            l.total_pay,
            COALESCE(
                pe.include_in_tip_pool,
                CASE
                    -- BAR 2 is a POS ordering profile, not an employee
                    WHEN UPPER(TRIM(l.first_name)) = 'BAR 2' AND UPPER(TRIM(l.last_name)) = 'BAR 2' THEN FALSE
                    ELSE TRUE
                END
            ) AS include_in_tip_pool,
            CASE
                WHEN pe.tip_pool_multiplier IS NOT NULL THEN pe.tip_pool_multiplier
                WHEN l.role = 'Bar Back' THEN (SELECT barback_multiplier FROM settings LIMIT 1)
                ELSE 1.0
            END AS tip_pool_multiplier
        FROM {_trusted_labor_subquery("l")}
        LEFT JOIN payroll_employee_settings pe
            ON COALESCE(l.employee_id, '') = pe.employee_id
            AND TRIM(l.first_name) = TRIM(pe.first_name)
            AND TRIM(l.last_name) = TRIM(pe.last_name)
        WHERE 1=1 {where}
        ORDER BY l.trading_day, l.last_name, l.first_name
    """, params)


def _get_tip_pool_cutoff(trading_day: date) -> datetime:
    """Return the tip pool cutoff datetime for a given trading_day.

    Sun-Thu trading days: 1:30 AM the next calendar day.
    Fri-Sat trading days: 3:30 AM the next calendar day.
    (weekday(): Mon=0 … Sun=6)
    """
    next_day = trading_day + timedelta(days=1)
    if trading_day.weekday() in (4, 5):  # Friday or Saturday
        return datetime.combine(next_day, time(3, 30))
    return datetime.combine(next_day, time(1, 30))


def _compute_tip_eligible_hours(
    shift_start: datetime | None,
    shift_end: datetime | None,
    total_hours: float,
    pool_start: datetime | None,
    cutoff: datetime,
) -> float:
    """Compute the portion of a shift that falls within [pool_start, cutoff].

    Returns *total_hours* unchanged when timestamps are missing (No-Shift entries)
    or when pool_start is unavailable.  Result is clamped to [0, total_hours].
    """
    if shift_start is None or shift_end is None or pool_start is None:
        return total_hours

    effective_start = max(shift_start, pool_start)
    effective_end = min(shift_end, cutoff)

    if effective_end <= effective_start:
        return 0.0

    eligible_hours = (effective_end - effective_start).total_seconds() / 3600.0
    return min(eligible_hours, total_hours)


def get_payroll_daily_allocations(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Per-day per-employee tip allocations (FOH pool split by weighted hours).

    Hours used for weighting are clipped to the tip pool time window:
      - Pool starts when the first bartender clocks in for the trading day.
      - Pool ends at 1:30 AM (Sun-Thu) or 3:30 AM (Fri-Sat) the next calendar day.

    Wages (total_pay) are NOT affected; only the tip pool weighting changes.
    Round to cents; distribute residual pennies by largest fractional remainder first.
    Columns: trading_day, employee_id, first_name, last_name, role,
             hours, tip_eligible_hours, weighted_hours, allocated_tips.
    """
    from decimal import Decimal, ROUND_HALF_UP

    inputs = get_payroll_daily_inputs(start, end)
    labor = get_payroll_labor_with_multiplier(start, end)
    if inputs.empty or labor.empty:
        return pd.DataFrame()

    labor = labor[labor["include_in_tip_pool"] == True]
    if labor.empty:
        return pd.DataFrame()

    labor["total_hours"] = labor["total_hours"].fillna(0).astype(float)
    labor["tip_pool_multiplier"] = labor["tip_pool_multiplier"].fillna(1.0).astype(float)

    # -- Tip pool window: determine pool_start per trading day --
    # Primary: earliest bartender clock-in; fallback: earliest shift of any role.
    pool_start_by_day: dict[date, datetime] = {}
    has_shift = labor["shift_start"].notna()

    bartender_shifts = labor[(labor["role"] == "Bartender") & has_shift]
    if not bartender_shifts.empty:
        for td, grp in bartender_shifts.groupby("trading_day"):
            pool_start_by_day[td] = pd.Timestamp(grp["shift_start"].min()).to_pydatetime()

    all_with_shifts = labor[has_shift]
    if not all_with_shifts.empty:
        for td, grp in all_with_shifts.groupby("trading_day"):
            if td not in pool_start_by_day:
                pool_start_by_day[td] = pd.Timestamp(grp["shift_start"].min()).to_pydatetime()

    # -- Compute tip-eligible hours per row --
    def _eligible(row):
        td = row["trading_day"]
        pool_start = pool_start_by_day.get(td)
        cutoff = _get_tip_pool_cutoff(td)
        ss = row["shift_start"]
        se = row["shift_end"]
        return _compute_tip_eligible_hours(
            shift_start=ss.to_pydatetime() if pd.notna(ss) else None,
            shift_end=se.to_pydatetime() if pd.notna(se) else None,
            total_hours=row["total_hours"],
            pool_start=pool_start,
            cutoff=cutoff,
        )

    labor["tip_eligible_hours"] = labor.apply(_eligible, axis=1)
    labor["weighted_hours"] = labor["tip_eligible_hours"] * labor["tip_pool_multiplier"]

    rows = []
    for trading_day, grp in labor.groupby("trading_day"):
        day_inputs = inputs[inputs["trading_day"] == trading_day]
        if day_inputs.empty:
            continue
        foh_pool = float(day_inputs.iloc[0]["foh_pool"])
        total_weighted = grp["weighted_hours"].sum()
        if total_weighted <= 0:
            continue

        shares = (grp["weighted_hours"] / total_weighted * foh_pool).values
        exact_cents = [round(s, 2) for s in shares]
        residual = round(foh_pool, 2) - sum(exact_cents)
        residual_cents = int(round(residual * 100))

        if residual_cents != 0:
            remainders = [(i, (shares[i] * 100) % 100) for i in range(len(shares))]
            remainders.sort(key=lambda x: -x[1])
            for j in range(abs(residual_cents)):
                idx = remainders[j % len(remainders)][0]
                if residual_cents > 0:
                    exact_cents[idx] += 0.01
                else:
                    exact_cents[idx] -= 0.01
                exact_cents[idx] = round(exact_cents[idx], 2)

        for (_, row), alloc in zip(grp.iterrows(), exact_cents):
            rows.append({
                "trading_day": trading_day,
                "employee_id": row["employee_id"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "role": row["role"],
                "hours": row["total_hours"],
                "tip_eligible_hours": row["tip_eligible_hours"],
                "weighted_hours": row["weighted_hours"],
                "allocated_tips": alloc,
            })

    return pd.DataFrame(rows)


def get_payroll_employees_list(active_days: int = None) -> pd.DataFrame:
    """Distinct employees (unique persons) from pos_labor for dropdown.
    Returns one row per person (employee_id, first_name, last_name) -- no role split.
    Excludes placeholder profiles like BAR 2 and any entry with a blank name.
    If active_days is set, only employees with a shift in the last N days are returned."""
    params = {}
    active_filter = ""
    if active_days is not None:
        active_filter = "AND trading_day >= CURRENT_DATE - INTERVAL :active_interval"
        params["active_interval"] = f"{active_days} days"

    return _q(f"""
        SELECT DISTINCT
            COALESCE(employee_id, '') AS employee_id,
            TRIM(first_name) AS first_name,
            TRIM(last_name) AS last_name
        FROM (
            SELECT pl.*
            FROM pos_labor pl
            JOIN import_logs il ON il.id = pl.import_log_id
            WHERE il.import_type = 'labor'
              AND il.status = 'success'
        ) l
        WHERE NOT (UPPER(TRIM(first_name)) = 'BAR 2' AND UPPER(TRIM(last_name)) = 'BAR 2')
          AND TRIM(COALESCE(first_name, '')) <> ''
          AND TRIM(COALESCE(last_name, '')) <> ''
          {active_filter}
        ORDER BY last_name, first_name
    """, params)


def get_payroll_employee_roles(employee_id: str = None, first_name: str = None,
                               last_name: str = None) -> list[str]:
    """Get all distinct roles for a specific employee."""
    where = "WHERE 1=1"
    params = {}
    if employee_id is not None:
        where += " AND COALESCE(employee_id, '') = :employee_id"
        params["employee_id"] = employee_id
    if first_name is not None:
        where += " AND TRIM(first_name) = TRIM(:first_name)"
        params["first_name"] = first_name
    if last_name is not None:
        where += " AND TRIM(last_name) = TRIM(:last_name)"
        params["last_name"] = last_name

    df = _q(f"""
        SELECT DISTINCT role
        FROM {_trusted_labor_subquery("l")}
        {where}
        ORDER BY role
    """, params)
    return df["role"].tolist() if not df.empty else []


def get_payroll_employee_wages(start: date = None, end: date = None,
                               employee_id: str = None, first_name: str = None,
                               last_name: str = None) -> pd.DataFrame:
    """Wages (total_pay, hours) per trading day, optionally filtered by one employee."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end
    if employee_id is not None:
        where += " AND COALESCE(employee_id, '') = :employee_id"
        params["employee_id"] = employee_id
    if first_name is not None:
        where += " AND TRIM(first_name) = TRIM(:first_name)"
        params["first_name"] = first_name
    if last_name is not None:
        where += " AND TRIM(last_name) = TRIM(:last_name)"
        params["last_name"] = last_name

    return _q(f"""
        SELECT trading_day, employee_id, first_name, last_name, role,
               reg_hours, ot_hours, (reg_hours + COALESCE(ot_hours, 0)) AS total_hours,
               total_pay
        FROM {_trusted_labor_subquery("l")}
        {where}
        ORDER BY trading_day
    """, params)


def get_payroll_cash_tips(start: date = None, end: date = None) -> pd.DataFrame:
    """Manual cash tip entries for date range."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND trading_day >= :start"
        params["start"] = start
    if end:
        where += " AND trading_day <= :end"
        params["end"] = end
    return _q(f"""
        SELECT id, trading_day, amount, notes, created_at
        FROM payroll_cash_tips
        {where}
        ORDER BY trading_day
    """, params)


def get_payroll_employee_settings() -> pd.DataFrame:
    """All payroll_employee_settings rows for Settings tab."""
    return _q("""
        SELECT id, employee_id, first_name, last_name,
               include_in_tip_pool, tip_pool_multiplier, updated_at
        FROM payroll_employee_settings
        ORDER BY last_name, first_name
    """)


# ============================================================================
# COGS DEEP DIVE
# ============================================================================


def get_cogs_trend(start: date = None, end: date = None, freq: str = "daily") -> pd.DataFrame:
    """
    COGS and revenue aggregated by day/week/month from product mix.
    Returns columns: period, total_cogs, net_revenue, cogs_pct.
    """
    params = {}
    where = "WHERE entry_type = 'Item'"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    if freq == "weekly":
        trunc = "DATE_TRUNC('week', report_start_date)"
    elif freq == "monthly":
        trunc = "DATE_TRUNC('month', report_start_date)"
    else:
        trunc = "report_start_date"

    return _q(f"""
        SELECT
            {trunc} AS period,
            COALESCE(SUM(CASE WHEN cost > 0 THEN cost ELSE 0 END), 0) AS total_cogs,
            COALESCE(SUM(net_sales), 0) AS net_revenue,
            CASE WHEN SUM(net_sales) > 0
                 THEN ROUND(SUM(CASE WHEN cost > 0 THEN cost ELSE 0 END)
                            / SUM(net_sales) * 100, 1)
                 ELSE 0 END AS cogs_pct
        FROM pos_product_mix
        {where}
          AND report_start_date = report_end_date
        GROUP BY {trunc}
        ORDER BY period
    """, params)


def get_cogs_vs_purchases(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Monthly theoretical COGS vs actual invoice purchases side-by-side.
    """
    params = {}
    cogs_where = "WHERE entry_type = 'Item' AND cost > 0 AND report_start_date = report_end_date"
    inv_where = "WHERE 1=1"
    if start:
        cogs_where += " AND report_start_date >= :start"
        inv_where += " AND invoice_date >= :start"
        params["start"] = start
    if end:
        cogs_where += " AND report_end_date <= :end"
        inv_where += " AND invoice_date <= :end"
        params["end"] = end

    return _q(f"""
        WITH monthly_cogs AS (
            SELECT
                DATE_TRUNC('month', report_start_date) AS month,
                SUM(cost) AS theoretical_cogs
            FROM pos_product_mix
            {cogs_where}
            GROUP BY DATE_TRUNC('month', report_start_date)
        ),
        monthly_purchases AS (
            SELECT
                DATE_TRUNC('month', invoice_date) AS month,
                SUM(total_amount) AS actual_purchases
            FROM inv_invoices
            {inv_where}
            GROUP BY DATE_TRUNC('month', invoice_date)
        )
        SELECT
            COALESCE(c.month, p.month) AS month,
            COALESCE(c.theoretical_cogs, 0) AS theoretical_cogs,
            COALESCE(p.actual_purchases, 0) AS actual_purchases
        FROM monthly_cogs c
        FULL OUTER JOIN monthly_purchases p ON c.month = p.month
        ORDER BY month
    """, params)


def get_cogs_by_category_trend(start: date = None, end: date = None) -> pd.DataFrame:
    """Category-level COGS over time (monthly) for stacked area chart."""
    params = {}
    where = "WHERE entry_type = 'Item' AND cost > 0 AND report_start_date = report_end_date"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            DATE_TRUNC('month', report_start_date) AS month,
            category_name,
            SUM(cost) AS total_cogs
        FROM pos_product_mix
        {where}
        GROUP BY DATE_TRUNC('month', report_start_date), category_name
        ORDER BY month, category_name
    """, params)


def get_top_cost_items(start: date = None, end: date = None, limit: int = 20) -> pd.DataFrame:
    """Items contributing the most total COGS dollars."""
    params = {"lim": limit}
    where = "WHERE entry_type = 'Item' AND cost > 0"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            item_name,
            category_name,
            SUM(cost) AS total_cost,
            SUM(net_sales) AS net_revenue,
            SUM(qty_sold) AS total_qty,
            CASE WHEN SUM(net_sales) > 0
                 THEN ROUND(SUM(cost) / SUM(net_sales) * 100, 1)
                 ELSE 0 END AS pour_cost_pct
        FROM pos_product_mix
        {where}
        GROUP BY item_name, category_name
        ORDER BY total_cost DESC
        LIMIT :lim
    """, params)


def get_worst_margin_items(start: date = None, end: date = None, limit: int = 20) -> pd.DataFrame:
    """Items with highest pour cost % (worst margins)."""
    params = {"lim": limit}
    where = "WHERE entry_type = 'Item' AND cost > 0"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            item_name,
            category_name,
            SUM(cost) AS total_cost,
            SUM(net_sales) AS net_revenue,
            SUM(qty_sold) AS total_qty,
            CASE WHEN SUM(net_sales) > 0
                 THEN ROUND(SUM(cost) / SUM(net_sales) * 100, 1)
                 ELSE 0 END AS pour_cost_pct
        FROM pos_product_mix
        {where}
        GROUP BY item_name, category_name
        HAVING SUM(net_sales) > 0
        ORDER BY pour_cost_pct DESC
        LIMIT :lim
    """, params)


def get_cost_coverage_gaps(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Items with revenue but no cost data -- biggest blind spots.
    Returns item_name, category, revenue, qty_sold.
    """
    params = {}
    where = "WHERE entry_type = 'Item' AND (cost IS NULL OR cost = 0)"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            item_name,
            category_name,
            SUM(net_sales) AS net_revenue,
            SUM(qty_sold) AS total_qty
        FROM pos_product_mix
        {where}
        GROUP BY item_name, category_name
        HAVING SUM(net_sales) > 0
        ORDER BY net_revenue DESC
    """, params)


def get_vendor_spend_trend(start: date = None, end: date = None) -> pd.DataFrame:
    """Monthly invoice spend by vendor for stacked chart."""
    params = {}
    where = "WHERE 1=1"
    if start:
        where += " AND i.invoice_date >= :start"
        params["start"] = start
    if end:
        where += " AND i.invoice_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            DATE_TRUNC('month', i.invoice_date) AS month,
            v.name AS vendor_name,
            SUM(i.total_amount) AS total_spend
        FROM inv_invoices i
        JOIN inv_vendors v ON i.vendor_id = v.id
        {where}
        GROUP BY DATE_TRUNC('month', i.invoice_date), v.name
        ORDER BY month, v.name
    """, params)


def get_vendor_spend_detail(vendor_name: str, start: date = None, end: date = None) -> pd.DataFrame:
    """Monthly spend trend for a single vendor."""
    params = {"vendor_name": vendor_name}
    where = "WHERE v.name = :vendor_name"
    if start:
        where += " AND i.invoice_date >= :start"
        params["start"] = start
    if end:
        where += " AND i.invoice_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            DATE_TRUNC('month', i.invoice_date) AS month,
            COUNT(DISTINCT i.id) AS invoice_count,
            SUM(i.total_amount) AS total_spend
        FROM inv_invoices i
        JOIN inv_vendors v ON i.vendor_id = v.id
        {where}
        GROUP BY DATE_TRUNC('month', i.invoice_date)
        ORDER BY month
    """, params)


def get_shrinkage_summary(start: date = None, end: date = None) -> pd.DataFrame:
    """
    Count variance aggregated by category.
    Joins count_lines to inv_items for category + unit_cost to get dollar variance.
    """
    params = {}
    where = "WHERE 1=1"
    if start:
        where += " AND c.count_date >= :start"
        params["start"] = start
    if end:
        where += " AND c.count_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            i.category,
            COUNT(cl.id) AS line_count,
            SUM(cl.variance) AS total_variance_units,
            SUM(cl.variance * COALESCE(i.unit_cost, 0)) AS total_variance_dollars,
            AVG(cl.variance_pct) AS avg_variance_pct
        FROM inv_count_lines cl
        JOIN inv_counts c ON cl.count_id = c.id
        JOIN inv_items i ON cl.inv_item_id = i.id
        {where}
        GROUP BY i.category
        ORDER BY total_variance_dollars
    """, params)


def get_high_variance_items(start: date = None, end: date = None, limit: int = 20) -> pd.DataFrame:
    """Items with largest dollar variance from inventory counts."""
    params = {"lim": limit}
    where = "WHERE 1=1"
    if start:
        where += " AND c.count_date >= :start"
        params["start"] = start
    if end:
        where += " AND c.count_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            i.name AS item_name,
            i.category,
            c.count_date,
            cl.counted_qty,
            cl.theoretical_qty,
            cl.variance,
            cl.variance_pct,
            cl.variance * COALESCE(i.unit_cost, 0) AS variance_dollars,
            i.unit_cost
        FROM inv_count_lines cl
        JOIN inv_counts c ON cl.count_id = c.id
        JOIN inv_items i ON cl.inv_item_id = i.id
        {where}
          AND cl.variance IS NOT NULL
        ORDER BY ABS(cl.variance * COALESCE(i.unit_cost, 0)) DESC
        LIMIT :lim
    """, params)


def get_adjustment_summary(start: date = None, end: date = None) -> pd.DataFrame:
    """Inventory adjustments by type with dollar totals."""
    params = {}
    where = "WHERE 1=1"
    if start:
        where += " AND a.adjustment_date >= :start"
        params["start"] = start
    if end:
        where += " AND a.adjustment_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            a.adjustment_type,
            COUNT(*) AS adjustment_count,
            SUM(a.quantity) AS total_units,
            SUM(a.quantity * COALESCE(i.unit_cost, 0)) AS total_dollars
        FROM inv_adjustments a
        JOIN inv_items i ON a.inv_item_id = i.id
        {where}
        GROUP BY a.adjustment_type
        ORDER BY total_dollars
    """, params)


def get_adjustment_trend(start: date = None, end: date = None) -> pd.DataFrame:
    """Monthly adjustment dollars by type for trend chart."""
    params = {}
    where = "WHERE 1=1"
    if start:
        where += " AND a.adjustment_date >= :start"
        params["start"] = start
    if end:
        where += " AND a.adjustment_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT
            DATE_TRUNC('month', a.adjustment_date) AS month,
            a.adjustment_type,
            SUM(a.quantity * COALESCE(i.unit_cost, 0)) AS total_dollars
        FROM inv_adjustments a
        JOIN inv_items i ON a.inv_item_id = i.id
        {where}
        GROUP BY DATE_TRUNC('month', a.adjustment_date), a.adjustment_type
        ORDER BY month, a.adjustment_type
    """, params)


def get_cost_data_health(start: date = None, end: date = None) -> dict:
    """
    Coverage stats: items with/without cost data, revenue covered vs uncovered.
    Returns a dict with summary stats and a category-level breakdown DataFrame.
    """
    params = {}
    where = "WHERE entry_type = 'Item'"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    totals = _q(f"""
        SELECT
            COUNT(DISTINCT item_name) AS total_items,
            COUNT(DISTINCT CASE WHEN cost > 0 THEN item_name END) AS items_with_cost,
            COALESCE(SUM(net_sales), 0) AS total_revenue,
            COALESCE(SUM(CASE WHEN cost > 0 THEN net_sales ELSE 0 END), 0) AS revenue_with_cost,
            COALESCE(SUM(CASE WHEN cost > 0 THEN cost ELSE 0 END), 0) AS total_cogs
        FROM pos_product_mix
        {where}
    """, params)

    by_category = _q(f"""
        SELECT
            category_name,
            COUNT(DISTINCT item_name) AS total_items,
            COUNT(DISTINCT CASE WHEN cost > 0 THEN item_name END) AS items_with_cost,
            COALESCE(SUM(net_sales), 0) AS total_revenue,
            COALESCE(SUM(CASE WHEN cost > 0 THEN net_sales ELSE 0 END), 0) AS revenue_with_cost
        FROM pos_product_mix
        {where}
        GROUP BY category_name
        ORDER BY total_revenue DESC
    """, params)

    row = totals.iloc[0]
    return {
        "total_items": int(row["total_items"]),
        "items_with_cost": int(row["items_with_cost"]),
        "total_revenue": float(row["total_revenue"]),
        "revenue_with_cost": float(row["revenue_with_cost"]),
        "total_cogs": float(row["total_cogs"]),
        "by_category": by_category,
    }


def get_cost_outlier_items(start: date = None, end: date = None) -> pd.DataFrame:
    """Items with suspiciously high or low cost ratios (outlier detection)."""
    params = {}
    where = "WHERE entry_type = 'Item' AND cost > 0"
    if start:
        where += " AND report_start_date >= :start"
        params["start"] = start
    if end:
        where += " AND report_end_date <= :end"
        params["end"] = end

    return _q(f"""
        WITH item_costs AS (
            SELECT
                item_name,
                category_name,
                SUM(cost) AS total_cost,
                SUM(net_sales) AS net_revenue,
                CASE WHEN SUM(net_sales) > 0
                     THEN ROUND(SUM(cost) / SUM(net_sales) * 100, 1)
                     ELSE 0 END AS pour_cost_pct
            FROM pos_product_mix
            {where}
            GROUP BY item_name, category_name
            HAVING SUM(net_sales) > 0
        )
        SELECT * FROM item_costs
        WHERE pour_cost_pct > 60 OR pour_cost_pct < 5
        ORDER BY pour_cost_pct DESC
    """, params)


# ============================================================================
# SCHEDULING
# ============================================================================


def get_employees(active_only: bool = True) -> pd.DataFrame:
    """Get employee roster from the master employees table."""
    where = "WHERE status = 'active'" if active_only else ""
    return _q(f"""
        SELECT id, pos_employee_id, first_name, last_name, primary_role,
               hire_date, status, max_hours_per_week, min_hours_per_week,
               phone, email, notes
        FROM employees
        {where}
        ORDER BY last_name, first_name
    """)


def get_employee_availability(employee_id: int = None) -> pd.DataFrame:
    """Get availability windows, optionally for one employee."""
    where = "WHERE (a.end_date IS NULL OR a.end_date >= CURRENT_DATE)"
    params = {}
    if employee_id is not None:
        where += " AND a.employee_id = :eid"
        params["eid"] = employee_id

    return _q(f"""
        SELECT a.id, a.employee_id, e.first_name, e.last_name,
               a.day_of_week, a.available_from, a.available_until,
               a.preference, a.effective_date, a.end_date, a.notes
        FROM employee_availability a
        JOIN employees e ON a.employee_id = e.id
        {where}
        ORDER BY e.last_name, e.first_name, a.day_of_week
    """, params)


def get_schedule_entries(start: date = None, end: date = None) -> pd.DataFrame:
    """Get published schedule entries for a date range."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND se.schedule_date >= :start"
        params["start"] = start
    if end:
        where += " AND se.schedule_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT se.id, se.employee_id, e.first_name, e.last_name,
               se.schedule_date, se.role, se.shift_start, se.shift_end,
               se.status, se.published_at, se.notes
        FROM schedule_entries se
        JOIN employees e ON se.employee_id = e.id
        {where}
        ORDER BY se.schedule_date, se.shift_start, e.last_name
    """, params)


def get_schedule_templates() -> pd.DataFrame:
    """Get all schedule templates with shift counts."""
    return _q("""
        SELECT t.id, t.name, t.day_type, t.notes,
               COUNT(s.id) AS shift_count,
               COALESCE(SUM(s.headcount), 0) AS total_headcount
        FROM schedule_templates t
        LEFT JOIN schedule_template_shifts s ON s.template_id = t.id
        GROUP BY t.id, t.name, t.day_type, t.notes
        ORDER BY t.day_type, t.name
    """)


def get_template_shifts(template_id: int) -> pd.DataFrame:
    """Get shift definitions for a specific template."""
    return _q("""
        SELECT id, role, shift_start, shift_end, headcount
        FROM schedule_template_shifts
        WHERE template_id = :tid
        ORDER BY shift_start, role
    """, {"tid": template_id})


def get_external_events(start: date = None, end: date = None) -> pd.DataFrame:
    """Get external events for a date range."""
    where = "WHERE 1=1"
    params = {}
    if start:
        where += " AND event_date >= :start"
        params["start"] = start
    if end:
        where += " AND event_date <= :end"
        params["end"] = end

    return _q(f"""
        SELECT id, event_date, event_time, venue, event_type,
               event_name, expected_impact, estimated_attendance, notes
        FROM external_events
        {where}
        ORDER BY event_date, event_time
    """, params)


def get_upcoming_events(days: int = 14) -> pd.DataFrame:
    """Get events in the next N days."""
    return _q("""
        SELECT id, event_date, event_time, venue, event_type,
               event_name, expected_impact, estimated_attendance
        FROM external_events
        WHERE event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + :days
        ORDER BY event_date, event_time
    """, {"days": days})


def get_scheduling_settings() -> pd.DataFrame:
    """Get the single-row scheduling settings."""
    return _q("""
        SELECT * FROM scheduling_settings ORDER BY id LIMIT 1
    """)
