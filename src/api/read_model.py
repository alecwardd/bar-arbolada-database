"""Least-privilege PostgreSQL read model for the manager API.

This module is intentionally independent from ``src.analytics.queries``.  The
Streamlit owner/operator dashboards have a much broader query surface; the
manager API must not inherit that surface accidentally.

Every query below selects only values needed to build a manager response.  The
machine-readable allowlist at the bottom is the exact PostgreSQL column set the
dedicated manager role needs to execute these queries.
"""

from __future__ import annotations

import json
import re
from datetime import date
from types import SimpleNamespace
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config import engine


SALES_DATE_RANGE_SQL = """
    SELECT
        MIN(trading_day) AS min_date,
        MAX(trading_day) AS max_date
    FROM public.pos_daily_sales
    WHERE net_sales IS NOT NULL
"""


DAILY_SALES_SQL = """
    SELECT
        trading_day,
        gross_sales,
        net_sales,
        total_guests,
        total_checks,
        guest_avg,
        check_avg,
        total_tips,
        total_comps,
        total_voids
    FROM public.pos_daily_sales
    WHERE trading_day >= :start
      AND trading_day <= :end
    ORDER BY trading_day
"""


HOURLY_HEATMAP_SQL = """
    SELECT
        EXTRACT(DOW FROM trading_day)::int AS dow,
        TO_CHAR(trading_day, 'Dy') AS dow_name,
        hour_of_day,
        AVG(net_sales) AS avg_net_sales,
        AVG(check_count) AS avg_checks,
        AVG(guest_count) AS avg_guests,
        COUNT(*) AS num_days
    FROM public.pos_hourly_sales
    WHERE trading_day >= :start
      AND trading_day <= :end
    GROUP BY
        EXTRACT(DOW FROM trading_day),
        TO_CHAR(trading_day, 'Dy'),
        hour_of_day
    ORDER BY dow, hour_of_day
"""


STAFFING_RUSH_SQL = """
    WITH trusted_labor AS (
        SELECT
            pl.trading_day,
            COALESCE(
                SUM(COALESCE(pl.reg_hours, 0) + COALESCE(pl.ot_hours, 0)),
                0
            ) AS total_hours,
            COALESCE(SUM(COALESCE(pl.total_pay, 0)), 0) AS pos_labor_cost
        FROM public.pos_labor AS pl
        JOIN public.import_logs AS il
          ON il.id = pl.import_log_id
        WHERE il.import_type = 'labor'
          AND il.status = 'success'
        GROUP BY pl.trading_day
    ),
    daily_inputs AS (
        SELECT
            s.trading_day,
            COALESCE(s.net_sales, 0) AS net_sales,
            COALESCE(tl.total_hours, 0) AS total_hours,
            COALESCE(tl.pos_labor_cost, 0)
                + COALESCE(fixed.fixed_labor_cost, 0) AS wages_cost,
            COALESCE(payroll.payroll_tax_rate, 0) AS payroll_tax_rate,
            COALESCE(payroll.payroll_fee_daily, 0) AS payroll_fee_daily
        FROM public.pos_daily_sales AS s
        LEFT JOIN trusted_labor AS tl
          ON tl.trading_day = s.trading_day
        LEFT JOIN LATERAL (
            SELECT COALESCE(SUM(f.daily_amount), 0) AS fixed_labor_cost
            FROM public.labor_fixed_daily_costs AS f
            WHERE f.include_in_projections = TRUE
              AND s.trading_day >= f.effective_start_date
              AND (
                    f.effective_end_date IS NULL
                    OR s.trading_day <= f.effective_end_date
                  )
        ) AS fixed ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                p.payroll_tax_rate,
                p.payroll_fee_monthly
                    / CAST(
                        DATE_PART(
                            'days',
                            DATE_TRUNC('month', s.trading_day)
                                + INTERVAL '1 month'
                                - DATE_TRUNC('month', s.trading_day)
                        )
                        AS NUMERIC
                    ) AS payroll_fee_daily
            FROM public.payroll_burden_settings AS p
            WHERE s.trading_day >= p.effective_start_date
              AND (
                    p.effective_end_date IS NULL
                    OR s.trading_day <= p.effective_end_date
                  )
            ORDER BY p.effective_start_date DESC
            LIMIT 1
        ) AS payroll ON TRUE
        WHERE s.trading_day >= :start
          AND s.trading_day <= :end
    ),
    daily_costs AS (
        SELECT
            trading_day,
            net_sales,
            total_hours,
            wages_cost
                + wages_cost * payroll_tax_rate
                + payroll_fee_daily AS total_labor_cost
        FROM daily_inputs
    )
    SELECT
        trading_day,
        net_sales,
        total_hours,
        total_labor_cost,
        CASE
            WHEN total_hours > 0
            THEN ROUND(net_sales / total_hours, 2)
            ELSE NULL
        END AS splh,
        CASE
            WHEN net_sales > 0
            THEN ROUND(total_labor_cost / net_sales * 100, 1)
            ELSE NULL
        END AS labor_pct
    FROM daily_costs
    ORDER BY trading_day
"""


PNL_SQL = """
    WITH sales_days AS (
        SELECT DISTINCT trading_day
        FROM public.pos_daily_sales
        WHERE trading_day >= :start
          AND trading_day <= :end
    ),
    revenue AS (
        SELECT COALESCE(SUM(net_sales), 0) AS net_sales
        FROM public.pos_daily_sales
        WHERE trading_day >= :start
          AND trading_day <= :end
    ),
    cogs AS (
        SELECT COALESCE(SUM(cost), 0) AS total_cogs
        FROM public.pos_product_mix
        WHERE entry_type = 'Item'
          AND cost > 0
          AND report_start_date >= :start
          AND report_end_date <= :end
    ),
    trusted_labor AS (
        SELECT
            pl.trading_day,
            COALESCE(SUM(COALESCE(pl.total_pay, 0)), 0) AS pos_labor_cost
        FROM public.pos_labor AS pl
        JOIN public.import_logs AS il
          ON il.id = pl.import_log_id
        WHERE il.import_type = 'labor'
          AND il.status = 'success'
          AND pl.trading_day >= :start
          AND pl.trading_day <= :end
        GROUP BY pl.trading_day
    ),
    fixed_labor AS (
        SELECT
            d.trading_day,
            COALESCE(SUM(f.daily_amount), 0) AS fixed_labor_cost
        FROM sales_days AS d
        LEFT JOIN public.labor_fixed_daily_costs AS f
          ON f.include_in_projections = TRUE
         AND d.trading_day >= f.effective_start_date
         AND (
                f.effective_end_date IS NULL
                OR d.trading_day <= f.effective_end_date
             )
        GROUP BY d.trading_day
    ),
    daily_labor AS (
        SELECT
            d.trading_day,
            COALESCE(t.pos_labor_cost, 0)
                + COALESCE(f.fixed_labor_cost, 0) AS wages_cost
        FROM sales_days AS d
        LEFT JOIN trusted_labor AS t
          ON t.trading_day = d.trading_day
        LEFT JOIN fixed_labor AS f
          ON f.trading_day = d.trading_day
    ),
    labor AS (
        SELECT COALESCE(
            SUM(
                dl.wages_cost
                    + dl.wages_cost * COALESCE(payroll.payroll_tax_rate, 0)
                    + COALESCE(payroll.payroll_fee_daily, 0)
            ),
            0
        ) AS total_labor_cost
        FROM daily_labor AS dl
        LEFT JOIN LATERAL (
            SELECT
                p.payroll_tax_rate,
                p.payroll_fee_monthly
                    / CAST(
                        DATE_PART(
                            'days',
                            DATE_TRUNC('month', dl.trading_day)
                                + INTERVAL '1 month'
                                - DATE_TRUNC('month', dl.trading_day)
                        )
                        AS NUMERIC
                    ) AS payroll_fee_daily
            FROM public.payroll_burden_settings AS p
            WHERE dl.trading_day >= p.effective_start_date
              AND (
                    p.effective_end_date IS NULL
                    OR dl.trading_day <= p.effective_end_date
                  )
            ORDER BY p.effective_start_date DESC
            LIMIT 1
        ) AS payroll ON TRUE
    ),
    operating_expenses AS (
        SELECT COALESCE(SUM(amount), 0) AS total_opex
        FROM public.op_expenses
        WHERE expense_date >= :start
          AND expense_date <= :end
    )
    SELECT
        revenue.net_sales,
        cogs.total_cogs,
        labor.total_labor_cost,
        operating_expenses.total_opex
    FROM revenue
    CROSS JOIN cogs
    CROSS JOIN labor
    CROSS JOIN operating_expenses
"""


CATEGORY_PROFITABILITY_SQL = """
    SELECT
        category_name,
        SUM(qty_sold) AS total_qty,
        SUM(net_sales) AS net_revenue,
        SUM(cost) AS total_cost,
        SUM(gross_profit) AS gross_profit,
        COUNT(DISTINCT item_name) AS unique_items
    FROM public.pos_product_mix
    WHERE entry_type = 'Item'
      AND report_start_date >= :start
      AND report_end_date <= :end
    GROUP BY category_name
    ORDER BY net_revenue DESC
"""


COST_HEALTH_TOTALS_SQL = """
    SELECT
        COUNT(DISTINCT item_name) AS total_items,
        COUNT(DISTINCT CASE WHEN cost > 0 THEN item_name END) AS items_with_cost,
        COALESCE(SUM(net_sales), 0) AS total_revenue,
        COALESCE(
            SUM(CASE WHEN cost > 0 THEN net_sales ELSE 0 END),
            0
        ) AS revenue_with_cost,
        COALESCE(
            SUM(CASE WHEN cost > 0 THEN cost ELSE 0 END),
            0
        ) AS total_cogs
    FROM public.pos_product_mix
    WHERE entry_type = 'Item'
      AND report_start_date >= :start
      AND report_end_date <= :end
"""


COST_HEALTH_BY_CATEGORY_SQL = """
    SELECT
        category_name,
        COUNT(DISTINCT item_name) AS total_items,
        COUNT(DISTINCT CASE WHEN cost > 0 THEN item_name END) AS items_with_cost,
        COALESCE(SUM(net_sales), 0) AS total_revenue,
        COALESCE(
            SUM(CASE WHEN cost > 0 THEN net_sales ELSE 0 END),
            0
        ) AS revenue_with_cost
    FROM public.pos_product_mix
    WHERE entry_type = 'Item'
      AND report_start_date >= :start
      AND report_end_date <= :end
    GROUP BY category_name
    ORDER BY total_revenue DESC
"""


LEDGER_CURRENT_SQL = """
    SELECT
        l.ledger_date,
        i.name AS item_name,
        i.category,
        i.unit_of_measure,
        i.par_level,
        i.reorder_point,
        l.closing_qty,
        l.days_of_cover,
        l.reorder_alert,
        v.name AS vendor_name
    FROM public.inv_daily_ledger AS l
    JOIN public.inv_items AS i
      ON l.inv_item_id = i.id
    LEFT JOIN public.inv_vendors AS v
      ON i.primary_vendor_id = v.id
    WHERE i.status = 'active'
      AND l.ledger_date = COALESCE(
            :as_of,
            (SELECT MAX(latest.ledger_date) FROM public.inv_daily_ledger AS latest)
          )
    ORDER BY l.reorder_alert DESC, i.name
"""


REORDER_ITEMS_SQL = """
    SELECT
        l.ledger_date,
        i.name AS item_name,
        i.category,
        i.unit_of_measure,
        i.par_level,
        i.reorder_point,
        l.closing_qty,
        l.days_of_cover,
        v.name AS vendor_name,
        v.lead_time_days
    FROM public.inv_daily_ledger AS l
    JOIN public.inv_items AS i
      ON l.inv_item_id = i.id
    LEFT JOIN public.inv_vendors AS v
      ON i.primary_vendor_id = v.id
    WHERE l.reorder_alert = TRUE
      AND l.ledger_date = (
            SELECT MAX(latest.ledger_date)
            FROM public.inv_daily_ledger AS latest
          )
      AND i.status = 'active'
    ORDER BY l.days_of_cover ASC NULLS FIRST
"""


IMPORT_RUN_SNAPSHOT_SQL = """
    SELECT
        source,
        messages_fetched,
        csv_attachments_saved,
        lookback_days,
        coverage_max_dates_json,
        missing_report_days_json,
        generated_on,
        created_at
    FROM public.import_run_snapshots
    ORDER BY created_at DESC, id DESC
    LIMIT 1
"""


RECENT_IMPORTS_SQL = """
    SELECT
        imported_at,
        import_type,
        report_date_start,
        report_date_end,
        row_count,
        status
    FROM public.import_logs
    ORDER BY imported_at DESC, id DESC
    LIMIT :limit
"""


READ_MODEL_SQL: dict[str, str] = {
    "sales_date_range": SALES_DATE_RANGE_SQL,
    "daily_sales": DAILY_SALES_SQL,
    "hourly_heatmap": HOURLY_HEATMAP_SQL,
    "staffing_rush": STAFFING_RUSH_SQL,
    "pnl": PNL_SQL,
    "category_profitability": CATEGORY_PROFITABILITY_SQL,
    "cost_health_totals": COST_HEALTH_TOTALS_SQL,
    "cost_health_by_category": COST_HEALTH_BY_CATEGORY_SQL,
    "ledger_current": LEDGER_CURRENT_SQL,
    "reorder_items": REORDER_ITEMS_SQL,
    "import_run_snapshot": IMPORT_RUN_SNAPSHOT_SQL,
    "recent_imports": RECENT_IMPORTS_SQL,
}


# Exact column privileges needed by READ_MODEL_SQL.  Keep this structure
# declarative and JSON-compatible through ``export_privilege_allowlist`` so an
# administrator can generate column-level GRANT statements without granting
# SELECT on any whole table.
MANAGER_READ_PRIVILEGES: dict[str, tuple[str, ...]] = {
    "import_logs": (
        "id",
        "import_type",
        "imported_at",
        "report_date_start",
        "report_date_end",
        "row_count",
        "status",
    ),
    "import_run_snapshots": (
        "id",
        "source",
        "messages_fetched",
        "csv_attachments_saved",
        "lookback_days",
        "coverage_max_dates_json",
        "missing_report_days_json",
        "generated_on",
        "created_at",
    ),
    "inv_daily_ledger": (
        "inv_item_id",
        "ledger_date",
        "closing_qty",
        "days_of_cover",
        "reorder_alert",
    ),
    "inv_items": (
        "id",
        "name",
        "category",
        "unit_of_measure",
        "par_level",
        "reorder_point",
        "primary_vendor_id",
        "status",
    ),
    "inv_vendors": (
        "id",
        "name",
        "lead_time_days",
    ),
    "labor_fixed_daily_costs": (
        "daily_amount",
        "effective_start_date",
        "effective_end_date",
        "include_in_projections",
    ),
    "op_expenses": (
        "expense_date",
        "amount",
    ),
    "payroll_burden_settings": (
        "payroll_tax_rate",
        "payroll_fee_monthly",
        "effective_start_date",
        "effective_end_date",
    ),
    "pos_daily_sales": (
        "trading_day",
        "gross_sales",
        "net_sales",
        "total_guests",
        "total_checks",
        "guest_avg",
        "check_avg",
        "total_tips",
        "total_comps",
        "total_voids",
    ),
    "pos_hourly_sales": (
        "trading_day",
        "hour_of_day",
        "net_sales",
        "check_count",
        "guest_count",
    ),
    "pos_labor": (
        "import_log_id",
        "trading_day",
        "reg_hours",
        "ot_hours",
        "total_pay",
    ),
    "pos_product_mix": (
        "report_start_date",
        "report_end_date",
        "entry_type",
        "item_name",
        "qty_sold",
        "cost",
        "net_sales",
        "gross_profit",
        "category_name",
    ),
}


_ROLE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def export_privilege_allowlist() -> dict[str, Any]:
    """Return a deterministic JSON-serializable column privilege manifest."""

    return {
        "version": 1,
        "schema": "public",
        "access": "SELECT",
        "tables": [
            {"table": table_name, "columns": list(columns)}
            for table_name, columns in sorted(MANAGER_READ_PRIVILEGES.items())
        ],
    }


def render_column_grants(role: str) -> str:
    """Render exact PostgreSQL column grants for a dedicated, unprivileged role."""

    if not _ROLE_IDENTIFIER.fullmatch(role):
        raise ValueError("role must be a lowercase PostgreSQL identifier")
    statements = [f"GRANT USAGE ON SCHEMA public TO {role};"]
    for table_name, columns in sorted(MANAGER_READ_PRIVILEGES.items()):
        statements.append(
            f"GRANT SELECT ({', '.join(columns)}) "
            f"ON TABLE public.{table_name} TO {role};"
        )
    return "\n".join(statements)


def _query_frame(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Execute one fixed read-model statement and return its bounded result."""

    with engine.connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})


def get_sales_date_range() -> tuple[date, date]:
    """Return the available manager sales range."""

    frame = _query_frame(SALES_DATE_RANGE_SQL)
    if (
        frame.empty
        or pd.isna(frame.iloc[0]["min_date"])
        or pd.isna(frame.iloc[0]["max_date"])
    ):
        today = date.today()
        return today, today
    return frame.iloc[0]["min_date"], frame.iloc[0]["max_date"]


def get_daily_sales(start: date, end: date) -> pd.DataFrame:
    """Return only daily fields present in the manager DTO."""

    return _query_frame(DAILY_SALES_SQL, {"start": start, "end": end})


def get_hourly_heatmap_data(start: date, end: date) -> pd.DataFrame:
    """Return aggregate hourly demand without check or employee detail."""

    return _query_frame(HOURLY_HEATMAP_SQL, {"start": start, "end": end})


def get_splh_trend(start: date, end: date) -> pd.DataFrame:
    """Return aggregate labor KPIs from trusted imports only."""

    return _query_frame(STAFFING_RUSH_SQL, {"start": start, "end": end})


def get_full_pnl(
    start: date,
    end: date,
    *,
    include_distributions: bool = False,
) -> dict[str, float]:
    """Return manager-safe operating P&L values.

    Owner distributions and retained cash are structurally unsupported by this
    read model; callers cannot opt into those tables.
    """

    if include_distributions:
        raise ValueError("Manager read model does not expose owner distributions.")

    frame = _query_frame(PNL_SQL, {"start": start, "end": end})
    if frame.empty:
        net_sales = cogs = labor_cost = total_opex = 0.0
    else:
        row = frame.iloc[0]
        net_sales = _safe_float(row.get("net_sales"))
        cogs = _safe_float(row.get("total_cogs"))
        labor_cost = _safe_float(row.get("total_labor_cost"))
        total_opex = _safe_float(row.get("total_opex"))

    gross_profit = net_sales - cogs
    prime_cost = cogs + labor_cost
    net_operating_income = gross_profit - labor_cost - total_opex
    return {
        "net_sales": net_sales,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": (gross_profit / net_sales * 100) if net_sales > 0 else 0.0,
        "labor_cost": labor_cost,
        "labor_pct": (labor_cost / net_sales * 100) if net_sales > 0 else 0.0,
        "prime_cost": prime_cost,
        "prime_cost_pct": (prime_cost / net_sales * 100) if net_sales > 0 else 0.0,
        "total_opex": total_opex,
        "opex_pct": (total_opex / net_sales * 100) if net_sales > 0 else 0.0,
        "net_operating_income": net_operating_income,
        "noi_pct": (net_operating_income / net_sales * 100 if net_sales > 0 else 0.0),
    }


def get_category_profitability(start: date, end: date) -> pd.DataFrame:
    """Return category aggregates only."""

    return _query_frame(
        CATEGORY_PROFITABILITY_SQL,
        {"start": start, "end": end},
    )


def get_cost_data_health(start: date, end: date) -> dict[str, Any]:
    """Return aggregate product-cost coverage."""

    params = {"start": start, "end": end}
    totals = _query_frame(COST_HEALTH_TOTALS_SQL, params)
    by_category = _query_frame(COST_HEALTH_BY_CATEGORY_SQL, params)
    if totals.empty:
        return {
            "total_items": 0,
            "items_with_cost": 0,
            "total_revenue": 0.0,
            "revenue_with_cost": 0.0,
            "total_cogs": 0.0,
            "by_category": by_category,
        }
    row = totals.iloc[0]
    return {
        "total_items": _safe_int(row.get("total_items")),
        "items_with_cost": _safe_int(row.get("items_with_cost")),
        "total_revenue": _safe_float(row.get("total_revenue")),
        "revenue_with_cost": _safe_float(row.get("revenue_with_cost")),
        "total_cogs": _safe_float(row.get("total_cogs")),
        "by_category": by_category,
    }


def get_ledger_current(as_of: date | None = None) -> pd.DataFrame:
    """Return the requested ledger snapshot using closing quantity as stock SoT."""

    return _query_frame(LEDGER_CURRENT_SQL, {"as_of": as_of})


def get_reorder_items() -> pd.DataFrame:
    """Return manager-visible reorder fields from the latest ledger day."""

    return _query_frame(REORDER_ITEMS_SQL)


def get_import_operations_rows(limit: int) -> tuple[Any | None, list[Any]]:
    """Return safe import-run fields without raw file or error metadata."""

    snapshot = None
    try:
        snapshot_frame = _query_frame(IMPORT_RUN_SNAPSHOT_SQL)
    except SQLAlchemyError:
        # A pre-migration local database can still serve safe recent import
        # summaries.  The failed statement runs on its own connection.
        snapshot_frame = pd.DataFrame()
    if not snapshot_frame.empty:
        snapshot = SimpleNamespace(**snapshot_frame.iloc[0].to_dict())

    logs_frame = _query_frame(RECENT_IMPORTS_SQL, {"limit": limit})
    logs = [SimpleNamespace(**row) for row in logs_frame.to_dict(orient="records")]
    return snapshot, logs


def _safe_float(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _safe_int(value: Any) -> int:
    if value is None or pd.isna(value):
        return 0
    return int(value)


if __name__ == "__main__":
    print(json.dumps(export_privilege_allowlist(), indent=2))
